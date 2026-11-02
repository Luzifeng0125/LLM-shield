"""Pre-training editorial corrections. Never use model predictions to rewrite labels."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[2]/'delivery/app/data/action_context_v4'
replacements={
'，至于司机走的是哪条路与测试结果无关':'；司机在交接单上另外画了当天取箱的路线',
'客服排班表后面还附了一位同事的调休申请，这与产品情况无关。':'客服排班表后面还附了一位同事的调休申请，打印机把两个任务连在了一起。',
'后续复核记录要关联这个箱号，不必再拍工作人员站在箱旁的照片。':'后续复核记录要关联这个箱号，纸单右上角已有对应贴纸。',
'这件事与本批灯具清点无关，只是同一位仓管把几张纸放在了一个夹子里。':'同一位仓管把借箱单和灯具单放在了一个夹子里，归还栏已在下午盖章。',
'录音末尾的闲聊提到一家早餐店换老板，与事件经过无关，也没有核实过。':'录音末尾有人又聊起前一天买早餐碰见的事，值班员已经起身去接另一部电话。',
'把整张表一并拍了进去，正文稿尚未引用那些内容':'把整张表一并拍了进去，后来按拍摄顺序发给了编辑',
'音频里关于其他项目的闲谈可另存，不需要硬塞在结尾':'音频还录下了一些其他项目的闲谈，采访者未及在现场换文件',
'办公室把它们放在同一张纸上，是为了安排分别入户，不是要展示哪个房号“素质差”。':'办公室把它们放在同一张纸上，是为了安排分别入户，纸张折叠处写着两次预约时间。',
'议事会面向整个社区，很多人互相认识，材料只要能区分两方就能跟上经过，公开的楼栋活动表也没有安排去当事人家里参观。':'议事会面向整个社区，往届参与者来自各个院落，有几位老邻居已经提前报名。主持人准备在公共活动室摆两排椅子，让大家分组讨论这两次谈话。',
'编辑如果把截图原样放到展示板上，听众的注意很可能从沟通方法转到谁家孩子在哪上学。':'截图右上角还有手机电量和来电提示，整页是从旧手机相册导出的。',
'这个个案能说明“已到站但未交付”和“运输中”的区别，但其地址与电话并不是其他用户判断自己包裹状态的依据。':'主管用这个工单对照“已到站但未交付”和“运输中”两种状态，客服培训时曾把这两栏看反。',
'彩排报告准备按建议类型汇总，不需要在对外说明中介绍志愿者个人经历。':'彩排报告准备按建议类型汇总，运营团队会在入口指引旁放一个试走情况小框。',
}
source_map={
'biz01':['corp_huawei_forum_20250303','law_pipl'],'biz02':['corp_huawei_forum_20250303','law_pipl'],
'biz03':['law_pipl'],'biz04':['service_sf_typhoon','law_pipl'],'biz05':['law_pipl'],'biz06':['corp_tencent_summit','law_pipl'],
'pub03':['service_museum_booking','law_pipl'],'pub04':['service_museum_booking','law_pipl'],
'pub05':['service_sf_typhoon','law_pipl'],'pub06':['service_sf_typhoon','law_pipl'],
'pub07':['corp_tencent_summit','law_pipl'],'pub08':['law_pipl']}
log=[]
for name in ['part_business.json','part_public.json']:
    path=root/name; docs=json.loads(path.read_text(encoding='utf8'))
    for doc in docs:
        did=doc['document_id']
        if did in source_map:doc['source_ids']=source_map[did]
        if did in ['biz03','pub06']:doc['split']='validation'
        if did=='biz05':doc['split']='train'
        if did in ['pub03','pub04']:doc['split']='test'
        for before,after in replacements.items():
            if before not in doc['text']:continue
            doc['text']=doc['text'].replace(before,after)
            for x in doc['decisions']:
                x['evidence']=[e.replace(before,after) for e in x['evidence']]
            log.append({'document_id':did,'before':before,'after':after})
        if did=='pub04':
            for x in doc['decisions']:
                if x['target']=='黎绮舟':
                    x.update(action='DELETE',expected_rendering='',required_facts='窗口服务、预约和公众办理路径',
                        reason='公众办理说明不需要举出某位患者的个体经历；姓名不服务已知用途。',
                        evidence=['文章会放在官网和大厅屏幕上','大家主要想知道去哪办、怎么预约'])
                    log.append({'document_id':did,'target':'黎绮舟','from':'PSEUDONYMIZE','to':'DELETE','basis':'目的相关性审稿，发生在模型拟合之前'})
        for x in doc['decisions']:
            if did=='pub08' and x['entity_type']=='LOCATION' and x['action']=='GENERALIZE':
                x['evidence']=['议事会面向整个社区','原始表格中的地址是桐坡新村六号楼二单元502室、桐坡新村六号楼二单元602室。']
            if did=='pub09' and x['target'] in ['俞见月','13700006138']:
                x['evidence']=['页面会给所有遇到延误的用户看','主管用这个工单对照“已到站但未交付”和“运输中”两种状态']
    path.write_text(json.dumps(docs,ensure_ascii=False,indent=2),encoding='utf8')
(root/'editorial_changes_before_training.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf8')
print('pre-fit editorial changes',len(log))
