========================================================================
field_v1 独立手写评测集 — 数据完整性校验报告
========================================================================

【1】偏移自洽
    text[start:end] 与实体文本一致：通过（0 处异常）

【2】取值多样性对照（旧 gold 的实体取值几乎不重复 → 说明它出自固定词表）
   field_v1 本集（87 条）
     API_KEY          n=5    distinct=5    取值复用率=0.00
     BANK_CARD        n=5    distinct=5    取值复用率=0.00
     BUDGET           n=11   distinct=11   取值复用率=0.00
     DORM             n=6    distinct=5    取值复用率=0.17
     EMAIL            n=11   distinct=11   取值复用率=0.00
     GRADE            n=5    distinct=5    取值复用率=0.00
     ID_CARD          n=4    distinct=4    取值复用率=0.00
     LOCATION         n=12   distinct=11   取值复用率=0.08
     ORG              n=10   distinct=10   取值复用率=0.00
     PERSON_NAME      n=51   distinct=39   取值复用率=0.24
     PHONE            n=14   distinct=12   取值复用率=0.14
     SENSITIVE_ATTR   n=6    distinct=6    取值复用率=0.00
     STUDENT_ID       n=5    distinct=3    取值复用率=0.40
     WECHAT           n=4    distinct=4    取值复用率=0.00
   gold_v3 旧人工集（312 条）
     API_KEY          n=8    distinct=8    取值复用率=0.00
     BANK_CARD        n=8    distinct=8    取值复用率=0.00
     BUDGET           n=36   distinct=36   取值复用率=0.00
     DORM             n=36   distinct=35   取值复用率=0.03
     EMAIL            n=36   distinct=36   取值复用率=0.00
     GRADE            n=36   distinct=24   取值复用率=0.33
     ID_CARD          n=8    distinct=8    取值复用率=0.00
     LOCATION         n=32   distinct=20   取值复用率=0.38
     ORG              n=8    distinct=7    取值复用率=0.12
     PERSON_NAME      n=112  distinct=112  取值复用率=0.00
     PHONE            n=60   distinct=60   取值复用率=0.00
     SENSITIVE_ATTR   n=8    distinct=5    取值复用率=0.38
     STUDENT_ID       n=36   distinct=36   取值复用率=0.00
     WECHAT           n=8    distinct=8    取值复用率=0.00

【3】格式真实性
   身份证通过 GB 11643 校验位 .... 4 通过 / 0 失败
   银行卡通过 Luhn 校验 .......... 5 通过 / 0 失败
   手机号号段（第二位）.......... {'3': 5, '5': 2, '7': 2, '8': 1}
   对照 —— 旧人工集的表面特征（模型只需记住这些即可拿满分）：
     身份证前 6 位地区码取值 .... ['999999']
     银行卡前 6 位 BIN 取值 ..... ['000000']
     手机号前 3 位号段 .......... ['130', '140', '150', '160', '170', '180', '190']
     邮箱域名取值 ............... ['example.invalid']
     密钥前缀取值 ............... ['SYNTHETIC_NO']
     微信号前缀取值 ............. ['wx_synth_']
     身份证取值去重后条数 ....... 8 / 8

【4】独立性：与各类训练语料的字符 n-gram 重合率
     口径：把训练语料的 n-gram 建成集合，统计 field_v1 有多少条记录命中过集合。
     越低说明本集越不是同源生成；高重合代表模型可以靠背模板而非理解上下文得分。

   (a) 人工 gold 训练集 —— 语料 196 条
      field_v1 :  6-gram 命中  5/87 条 (  5.7%)
      field_v1 :  8-gram 命中  2/87 条 (  2.3%)
      field_v1 : 10-gram 命中  0/87 条 (  0.0%)
      field_v1 : 12-gram 命中  0/87 条 (  0.0%)
      [对照] 旧人工 test 集 80 条中 63 条命中 ( 78.8%)

   (b) 旧模板训练集 —— 语料 196 条
      field_v1 :  6-gram 命中  5/87 条 (  5.7%)
      field_v1 :  8-gram 命中  2/87 条 (  2.3%)
      field_v1 : 10-gram 命中  0/87 条 (  0.0%)
      field_v1 : 12-gram 命中  0/87 条 (  0.0%)
      [对照] 旧人工 test 集 80 条中 63 条命中 ( 78.8%)

   (c) 自举增强集 —— 语料 220 条
      field_v1 :  6-gram 命中 18/87 条 ( 20.7%)
      field_v1 :  8-gram 命中  8/87 条 (  9.2%)
      field_v1 : 10-gram 命中  1/87 条 (  1.1%)
      field_v1 : 12-gram 命中  1/87 条 (  1.1%)
      [对照] 旧人工 test 集 80 条中 68 条命中 ( 85.0%)

   残留重合的 8-gram 全量（共 17 个）：
      .edu.cn。                 x3
      号：621700                 x1
      卡号：62170                 x1
      ：6217001                 x1
      62122612                 x1
      账户621226                 x1
      息：440305                 x1
      信息：44030                 x1
      20106200                 x1
      api_key=                 x1
      key=Club                 x1
      _key=Clu                 x1
      pi_key=C                 x1
      ey=Club2                 x1
      i_key=Cl                 x1
      password                 x1
      assword=                 x1

【5】分布
   实体 149 个 / 14 类
     API_KEY          5
     BANK_CARD        5
     BUDGET           11
     DORM             6
     EMAIL            11
     GRADE            5
     ID_CARD          4
     LOCATION         12
     ORG              10
     PERSON_NAME      51
     PHONE            14
     SENSITIVE_ATTR   6
     STUDENT_ID       5
     WECHAT           4
   纯负例（无任何敏感实体）17 / 87 条 = 20%
   场景数 68

