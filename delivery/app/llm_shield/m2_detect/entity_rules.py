"""语义实体识别：中文姓名 / 机构 / 地点 / 敏感属性。

对应架构 ② 的「语义实体：姓名/机构/地点（中文NER）」。
用「姓氏表 + 称谓上下文 + 机构后缀 + 敏感词表 + 表格列名」的启发式方案，
保证 CPU 单并发下 P95 远低于 500ms。

它与 GLiNER 的分工：
- GLiNER **关闭**时，本检测器是唯一的语义实体来源；
- GLiNER **开启**时，本检测器关闭机构/地点规则（`detect_org_location=False`），
  因为词典的贪婪前缀边界偏宽（会把「的地点为」这类引入词一并框入），
  由 GLiNER 提供精确边界；姓名/敏感属性/列名检测仍然保留，做双保险。

精度优先策略：姓名必须命中姓氏表且带称谓/职务上下文，或来自「姓名」类表格列，
否则不标注，避免把「明天」「高中」这类词误判成人名。
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..schema import Span
from .base import Detector

# ---------------------------------------------------------------- 词典

# 常见中文姓氏（含复姓）
SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章"
    "云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常"
    "乐于时傅皮齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊"
    "纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞"
    "万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑裴陆荣翁荀"
    "羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁"
    "仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池"
    "乔阴鬱胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍卻璩桑桂濮牛寿通边扈燕冀郏浦尚农温"
    "别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧"
    "殳沃利蔚越夔隆师巩厍聂晁冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯"
    "盖益桓公"
)
# 复姓补充
COMPOUND_SURNAMES = ["欧阳", "上官", "司马", "东方", "独孤", "南宫", "万俟", "闻人", "夏侯",
                     "诸葛", "赫连", "皇甫", "尉迟", "公孙", "慕容", "长孙", "宇文", "司徒",
                     "司空", "令狐", "轩辕", "百里", "呼延", "东郭", "南门", "西门"]

# 称谓 / 职务标签，必须与姓名直接相连，不能仅凭附近出现职务词。
PERSON_TITLES = [
    "负责人", "同学", "老师", "部长", "主席", "副主席", "会长", "副会长", "团长", "队长",
    "组长", "干事", "部长", "秘书长", "书记", "副书记", "辅导员", "教授", "助教", "学长",
    "学姐", "学弟", "学妹", "主任", "经理", "主管", "成员", "队员", "选手", "作者", "申报人",
    "联系人", "申请人", "主讲", "嘉宾", "志愿者", "同学", "同志", "师傅", "指导", "带队",
    # 表格/表单字段标签：出现「姓名：张三」这类结构时，其后即为人名
    "姓名", "名字", "名单", "报名人", "经办人", "填报人",
    # 会议场景：主持人、参会人同样指向具体个人
    "主持人", "参会", "与会", "出席", "列席", "记录人", "参会人员", "与会人员", "参会人",
    # 分工动词：「刘洋负责测试与上线」这类写法没有称谓词，只有动词。
    # 不加进来，「负责/牵头/协助」后面的姓名会整段漏召回。
    "负责", "牵头", "分管", "主导", "承担", "协助", "统筹", "对接", "跟进", "报送",
    "联络", "协调", "经办", "主讲人",
]

# 机构后缀词
#
# 注意：「系」已从通用后缀中移出，改由 _ORG_DEPT_RE 单独收紧判定。
# 放在这里时，贪婪前缀 + 回溯会让「实际系（统）」「（联）系」「（院）系」这类
# 普通词整段被框成机构名——实测一次评测里 4 个 ORG 误报有 3 个来自「系」。
ORG_SUFFIXES = [
    "学生会", "研究生会", "社团", "协会", "研究会", "俱乐部", "志愿者协会", "团委", "团支部",
    "学院", "大学", "学校", "实验室", "研究中心", "服务中心", "数据中心", "信息中心",
    "工作室", "团队", "组委会", "理事会",
    "公司", "基金会", "书院", "学部",
    # 注意：泛化的「中心」不在此列——「学生活动中心」是地点而非机构，
    # 保留它会把大量校内场所误判成 ORG
]

# 地点后缀词
LOC_SUFFIXES = [
    "楼", "教室", "会议室", "报告厅", "操场", "体育馆", "图书馆", "食堂", "礼堂", "活动中心",
    "广场", "展厅", "咖啡厅", "多功能厅", "楼前", "路", "门",
    # 「处」按校内惯例指办公场所（后勤处/教务处/登记处），归为地点。
    # 但「处理/到处/好处/长处」这类常用词必须挡掉，否则误报遍地。
    "处",
]

# 「处」后面紧跟这些字时，「处」是另一个词的首字而非地点后缀：
# 处理 / 处于 / 处所 / 处罚 / 处境 / 处置 / 处分。
# 「这个问题处理起来」曾被框成地点「这个问题处」。
CHU_FOLLOW_BAD = frozenset("理所于罚境置分")

# 「XX处」中的常见非地点词，命中即丢弃
LOC_STOPWORDS = {
    "路上", "门口", "门前", "门后",
    "处理", "到处", "此处", "该处", "一处", "多处", "各处", "每处", "别处", "近处",
    "远处", "深处", "四处", "处处", "好处", "坏处", "难处", "用处", "害处", "错处",
    "苦处", "痛处", "短处", "长处", "难处", "处于", "处事",
}

# 敏感个人属性关键词（出现即高敏）
SENSITIVE_WORDS = [
    "政治面貌", "中共党员", "预备党员", "共青团员", "民主党派", "群众", "宗教", "信仰",
    "佛教", "基督教", "伊斯兰教", "民族", "汉族", "回族", "藏族", "维吾尔", "壮族",
    "病史", "病历", "抑郁症", "焦虑症", "残疾", "精神疾病", "传染病", "药物过敏",
    "贫困生", "低保", "助学金", "家庭困难", "单亲", "离异", "性取向", "婚育",
]

# 表格列名 → 敏感类别（模块 ② 的「结构化材料结合列名判断」）
COLUMN_CATEGORY_HINTS = {
    "姓名": "PERSON_NAME", "名字": "PERSON_NAME", "负责人": "PERSON_NAME",
    "成员": "PERSON_NAME", "联系人": "PERSON_NAME", "申请人": "PERSON_NAME",
    "申报人": "PERSON_NAME", "参与人": "PERSON_NAME", "主讲人": "PERSON_NAME",
    "手机号": "PHONE", "电话": "PHONE", "联系方式": "PHONE", "联系电话": "PHONE",
    "邮箱": "EMAIL", "电子邮箱": "EMAIL", "邮件": "EMAIL",
    "身份证": "ID_CARD", "身份证号": "ID_CARD", "证件号": "ID_CARD",
    "学号": "STUDENT_ID", "学籍号": "STUDENT_ID",
    "银行卡": "BANK_CARD", "银行卡号": "BANK_CARD", "卡号": "BANK_CARD",
    "宿舍": "DORM", "宿舍号": "DORM", "住址": "DORM", "家庭住址": "DORM",
    "成绩": "GRADE", "绩点": "GRADE", "GPA": "GRADE", "平均分": "GRADE",
    "政治面貌": "SENSITIVE_ATTR", "民族": "SENSITIVE_ATTR",
    "预算": "BUDGET", "金额": "BUDGET", "经费": "BUDGET", "费用": "BUDGET",
    "微信": "WECHAT", "微信号": "WECHAT", "QQ": "WECHAT",
    "社团": "ORG", "组织": "ORG", "单位": "ORG", "学院": "ORG", "部门": "ORG",
    "地点": "LOCATION", "活动地点": "LOCATION", "场地": "LOCATION",
}


class EntityDetector(Detector):
    """语义实体识别器（词典 + 上下文 + 列名）。"""

    name = "entity"

    def __init__(self, detect_org_location: bool = True):
        """当 GLiNER 语义模型激活时，词典的 ORG/LOCATION 贪婪正则会产生边界过宽的
        误报（把「写作/记录为/的地点为」等引入词一并框入），故可由调用方关闭，
        改由 GLiNER 提供精确边界。人名/敏感属性/列名检测仍保留。"""
        self.detect_org_location = detect_org_location

    # 姓名：复姓或单姓 + 1~2 个汉字
    #
    # 注意：这里刻意**不加**「前一个字符必须是非汉字」的前瞻断言。
    # 「负责人张明」中「张」的前一个字是「人」，一旦加上该断言就永远匹配不到，
    # 自由文本里的姓名召回率会接近 0（早期版本正是这个 bug，
    # 只有表格列名命中的姓名能被识别出来）。
    # 误报改由三重机制控制：姓氏表 + 停用词表 + 称谓上下文。
    # 首字只允许姓氏表内的字（或复姓）。
    # 若像早期版本那样允许任意汉字开头，「负责人张明」会先被匹配成「人张明」，
    # finditer 消耗掉这段后就跳过了真正的「张明」，造成漏召回。
    _SURNAME_CHARSET = "[" + "".join(sorted(SURNAMES)) + "]"
    _NAME = r"(?:" + "|".join(COMPOUND_SURNAMES) + r"|" + _SURNAME_CHARSET + r")[\u4e00-\u9fa5]{1,2}"
    _TITLES = "|".join(sorted(set(PERSON_TITLES), key=len, reverse=True))
    _PERSON_RE = re.compile(_NAME + r"(?=$|[^\u4e00-\u9fa5]|[和与及]|" + _TITLES + r")")
    _PREFIX_RE = re.compile(r"(?:" + _TITLES + r")[ \t]*(?:[：:为是][ \t]*)?")
    # 前一个字符原只允许「非汉字 / 由请和与及」，于是「计算机学院的周涛同学」
    # 这种最常见的「的」字结构整段漏召回——而它恰恰是会把姓名带去公开场合的句式。
    # 放开常见虚词前缀；误报由姓氏表 + 停用词表 + 后置称谓三重约束兜住。
    _NAME_PRE_CHARS = "由请和与及的了是在有"
    _SUFFIX_RE = re.compile(r"(?:^|[^\u4e00-\u9fa5]|[" + _NAME_PRE_CHARS + r"])(?P<name>" + _NAME
                            + r")(?=[（(]?(?:" + _TITLES + r"))")
    _LIST_SEPARATOR = re.compile(r"[ \t]*[、,，和与及][ \t]*")
    # 专名主体的「断点字」：动词、介词、助词、连词。
    #
    # 用无约束的 [\u4e00-\u9fa5]{2,12} 做前缀时，贪婪回溯会把整段引导语框进来：
    # 「申请由赵磊提交至后勤处」被判成地点「申请由赵磊提交至后勤处」。
    # 改成「不含断点字的连续串」（tempered greedy）：从后缀往左遇到断点字即止，
    # 于是上面这句正确落在「后勤处」。刻意不收 会/动/活/和/同/向/正 等字——
    # 它们是「学生活动中心」「校学生会」「和平路」「同济大学」的组成部分。
    _BREAKCHARS = "的了着过是在有与及或把将被给让叫由从到至以于对还就都也又再才更很曾请使令作为"
    _BODY = r"(?:(?![{}])[\u4e00-\u9fa5A-Za-z0-9])".format(_BREAKCHARS)

    _ORG_RE = re.compile(_BODY + r"{2,12}(?:" + "|".join(ORG_SUFFIXES) + r")")
    _LOC_RE = re.compile(_BODY + r"{1,10}(?:" + "|".join(LOC_SUFFIXES) + r")")

    # 「XX系」单独判定（见 ORG_SUFFIXES 注释）：
    #   ① 后面不能紧跟 统/列/数 —— 那是「系统 / 系列 / 系别」，不是院系；
    #   ② 「系」前一字落进 _DEPT_BAD_PREV —— 那是「联系 / 关系 / 体系 / 派系」等常用词；
    #   ③ 主体至少 2 个字 —— 单字 + 「系」不成机构名。
    _ORG_DEPT_RE = re.compile(_BODY + r"{2,6}系(?![统列数])")
    _DEPT_BAD_PREV = frozenset("联关体世派母嫡")

    # 机构名左侧的引导词：贪婪前缀常把动词/介词一并框进来
    # （「覆盖计算机学院」→ 实为「计算机学院」）。
    _ORG_LEADIN_2 = (
        "覆盖", "辐射", "包括", "包含", "依托", "联合", "承办", "主办", "协办", "来自",
        "前往", "位于", "走进", "走访", "面向", "针对", "关于", "以及", "还有", "例如",
        "比如", "所在", "所属", "下设", "隶属", "挂靠", "成立", "组建", "搭建", "建设",
        "创建", "加入", "参加", "参与", "通知", "拜访", "访问", "调研", "考察", "参观",
        "服务", "支持", "感谢", "委托", "授权", "会同", "携手", "对接", "沟通", "汇报",
        "请示", "报备", "申报", "提交", "报送", "抄送", "合作", "签约", "共建", "招募",
        "联络", "联系", "协调", "统筹", "对接", "邀请", "召集", "发动", "动员",
    )
    # 机构名左侧的限定词单字（永远不会是专名开头）
    _ORG_LEADIN_1 = frozenset("各本该此全多数几每整")

    # 姓名末字禁用字：贪婪匹配会把「陈静共5人」的「共」一起吃进来。
    # 末字落在这些连接/总括/助词上，说明名字已经越界，回退到最短合法长度。
    _NAME_TAIL_STOP = frozenset("共等及与和的在了是也就都还要将会可已被把让给向从为以地得着过")

    # 明显不是人名的常见词（姓氏开头的误报词）
    _PERSON_STOPWORDS = {
        "明天", "明白", "明星", "周末", "周报", "周期", "周一", "周二", "周三", "周四", "周五", "周六", "周日", "王子", "王朝", "王朝", "李子",
        "陈年", "陈旧", "陈述", "陈列", "何事", "何必", "为何", "吕布", "张望", "张开",
        "张开", "张口", "文章", "文件", "文具", "文化", "文明", "文学", "文字",
        "黄金", "黄河", "金奖", "金秋", "清明", "清楚", "清晨", "清晨", "清晰",
        "高中", "高兴", "高度", "高校", "高考", "高等", "高级",
        "林立", "林业", "林木", "徐徐", "徐步", "许多", "许可", "序号",
        "业余", "余下", "余额", "于此", "于是", "于此", "于此",
        "史学", "使命", "使用", "例如", "例如", "东风", "东西", "东部",
        "南京", "南方", "南门", "南海", "南海", "作业", "作品", "作为",
        "曾经", "曾孙", "增加", "增长", "赠与", "孟买", "孟子",
        "常规", "常见", "常用", "常常", "康健", "健康", "康复",
        "平原", "平时", "平行", "平均", "平衡", "平静",
        "旺季", "王朝", "汪洋", "汪汪", "毛泽东", "周恩来",
        # 校园高频词：首字恰好落在姓氏表内（宿/成/项/纪/计/时…），
        # 不加进停用词就会被误判成人名——实测「宿舍」就被判成了 PERSON_NAME
        "宿舍", "成员", "项目", "纪要", "计划", "时间", "建议",
        "经费", "预算", "进度", "任务", "事项", "期限", "学期",
        "学号", "成果", "成效", "总结", "内容", "流程", "结果",
        "问题", "下一步", "主办", "承办", "学院", "班级", "小组",
        "部门", "组织", "社团", "活动", "会议", "学历",
        # 职务/身份词同样会被姓氏规则命中（宿/组/部…），一并排除
        "宿舍长", "舍长", "组长", "团长", "队长", "班长",
    }

    def detect(self, text: str, columns=None, rows=None) -> List[Span]:
        spans: List[Span] = []
        if not text:
            return spans

        spans += self._detect_sensitive_attrs(text)
        if self.detect_org_location:
            spans += self._detect_org(text)
            spans += self._detect_location(text)
        spans += self._detect_person(text)
        spans += self._detect_from_columns(text, columns, rows)
        return spans

    # ------------------------------------------------------------ 各类别

    @classmethod
    def _trim_name_tail(cls, value: str) -> str:
        """裁掉被贪婪后缀吃进姓名的虚词。

        「陈静共5人」会被 _PERSON_RE 匹配成「陈静共」（「5」是非汉字，满足后瞻），
        于是「陈静」这个真名既不进 names，全文的其它「陈静」提及也全部漏召回。
        末字是连接/总括/助词时回退到最短合法长度（≥2 字）。
        """
        while len(value) > 2 and value[-1] in cls._NAME_TAIL_STOP:
            value = value[:-1]
        return value

    def _detect_person(self, text: str) -> List[Span]:
        """先定位标签或称谓直接指向的姓名，再覆盖同文中的同名提及。"""
        out: List[Span] = []
        names = set()
        for title in self._PREFIX_RE.finditer(text):
            cursor = title.end()
            while match := self._PERSON_RE.match(text, cursor):
                name = self._trim_name_tail(match.group())
                if match.group() in self._PERSON_STOPWORDS or name in self._PERSON_STOPWORDS:
                    break
                names.add(name)
                # 用裁剪后的边界继续找并列项，否则「陈静共5人」会把游标推过分隔符
                separator = self._LIST_SEPARATOR.match(text, match.start() + len(name))
                if separator is None:
                    break
                cursor = separator.end()
        for match in self._SUFFIX_RE.finditer(text):
            name = self._trim_name_tail(match.group("name"))
            if name not in self._PERSON_STOPWORDS:
                names.add(name)
        for value in sorted(names):
            cursor = 0
            while (start := text.find(value, cursor)) >= 0:
                out.append(Span(start, start + len(value), value, "PERSON_NAME", 0.82,
                                self.name, "person_surname_title"))
                cursor = start + len(value)
        return out

    @classmethod
    def _trim_org(cls, value: str) -> str:
        """修机构名的左右边界。

        右：「经济管理学院等主要院系」把总括语一起框了进来，止于「等」之前。
        左：「覆盖计算机学院」里的「覆盖」是动词，不是机构名的一部分。
        """
        idx = value.find("等")
        if 2 <= idx < len(value) - 1:
            value = value[:idx]
        changed = True
        while changed and len(value) > 3:
            changed = False
            for lead in cls._ORG_LEADIN_2:
                if value.startswith(lead) and len(value) - len(lead) >= 2:
                    value = value[len(lead):]
                    changed = True
                    break
            if changed:
                continue
            if value[0] in cls._ORG_LEADIN_1 and len(value) > 3:
                value = value[1:]
                changed = True
        return value

    def _detect_org(self, text: str) -> List[Span]:
        out: List[Span] = []
        for m in self._ORG_RE.finditer(text):
            end = m.end()
            value = self._trim_org(m.group(0))
            if len(value) < 3:
                continue
            out.append(Span(end - len(value), end, value, "ORG", 0.80, self.name, "org_suffix"))
        for m in self._ORG_DEPT_RE.finditer(text):
            end = m.end()
            raw = m.group(0)
            if raw[-2] in self._DEPT_BAD_PREV:      # 联系 / 关系 / 体系 …
                continue
            value = self._trim_org(raw)
            if len(value) < 3:
                continue
            out.append(Span(end - len(value), end, value, "ORG", 0.78, self.name, "org_dept"))
        return out

    def _detect_location(self, text: str) -> List[Span]:
        out: List[Span] = []
        for m in self._LOC_RE.finditer(text):
            value = m.group(0)
            if len(value) < 2:
                continue
            # 「路上」「门口」「处理」「到处」之类不构成地点
            if value in LOC_STOPWORDS:
                continue
            if value.endswith("处") and m.end() < len(text) \
                    and text[m.end()] in CHU_FOLLOW_BAD:
                continue
            out.append(Span(m.start(), m.end(), value, "LOCATION", 0.75, self.name, "loc_suffix"))
        return out

    def _detect_sensitive_attrs(self, text: str) -> List[Span]:
        out: List[Span] = []
        for word in SENSITIVE_WORDS:
            start = 0
            while True:
                idx = text.find(word, start)
                if idx < 0:
                    break
                out.append(Span(idx, idx + len(word), word, "SENSITIVE_ATTR", 0.92,
                                self.name, "sensitive_word"))
                start = idx + len(word)
        return out

    def _detect_from_columns(self, text: str, columns: Optional[List[str]],
                             rows: Optional[List[dict]]) -> List[Span]:
        """结构化表格：命中敏感列名的单元格值，按列名映射到类别。

        这是架构 ② 中「结构化材料结合列名判断」的落地：
        列名给了强先验，比在自由文本里猜可靠得多。
        """
        out: List[Span] = []
        if not rows or not columns:
            return out
        for row in rows:
            for col in columns:
                value = str(row.get(col, "") or "").strip()
                if not value:
                    continue
                category = COLUMN_CATEGORY_HINTS.get(str(col).strip())
                if not category:
                    continue
                # 在正文中定位该单元格值（可能多处，全部标注）
                start = 0
                while True:
                    idx = text.find(value, start)
                    if idx < 0:
                        break
                    out.append(Span(idx, idx + len(value), value, category, 0.95,
                                    self.name, "column_hint", column=str(col)))
                    start = idx + len(value)
        return out
