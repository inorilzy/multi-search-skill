> Source: https://cloud.baidu.com/doc/qianfan-api/s/wmjqtqr7w
> Retrieved: 2026-10-31
> Covers: POST https://qianfan.baidubce.com/v2/ai_search/web_summary (智能搜索生成（高性能版）) request params + response schema

# 智能搜索生成（高性能版）

更新时间：2026-09-30

POST

https://qianfan.baidubce.com/v2/ai_search/web_summary

[调试](https://console.bce.baidu.com/support/?timestamp=1771930734399#/api?product=QIANFAN&project=%E5%8D%83%E5%B8%86Agent%E5%BC%80%E5%8F%91%E5%B9%B3%E5%8F%B0&parent=%E7%99%BE%E5%BA%A6AI%E6%90%9C%E7%B4%A2&api=v2%2Fai_search%2Fweb_summary&method=post)

**概述：** 智能搜索生成高性能版整合了大模型与搜索的能力，可根据用户输入的query进行全网实时信息检索，并总结输出内容。高性能版具有快的响应速度，同时不再区分搜索费用和大模型费用，仅按照调用量收费。

**计费：** 每日免费额度为100次，支持按量后付费（为不影响使用体验，可先去[开通后付费](https://console.bce.baidu.com/ai_apaas/resource)），默认优先抵扣免费资源的免费额度，费用详情请查看[计费说明](https://cloud.baidu.com/doc/qianfan/s/8miy9o4o6)。

**使用方式：** API

## 权限说明[](https://cloud.baidu.com/doc/qianfan-api/s/wmjqtqr7w#%E6%9D%83%E9%99%90%E8%AF%B4%E6%98%8E)

调用本API，需使用API Key鉴权方式。使用API Key鉴权调用API流程，具体调用流程，请查看[认证鉴权](https://cloud.baidu.com/doc/qianfan/s/Kmh4sutww)。

## 请求参数[](https://cloud.baidu.com/doc/qianfan-api/s/wmjqtqr7w#%E8%AF%B7%E6%B1%82%E5%8F%82%E6%95%B0)

Headers 参数

除公共头域外，无其它特殊头域

Body 参数

 instruction string

人设指令，用于设定模型的输出角色与表达风格，对生成内容的语气、风格等进行约束。

可选

 messages object {2}

对话历史 array的长度需要是奇数, role必须是user-assistant-user交替，以user开始以user结束。仅搜索时按照获取最后一次对话，作为搜索query。  
  
例子：[{"role": "user", "content":"你觉得xx的发布会上把xx的100pro手机的芯片搞错了需要道歉吗"},{"role": "assistant", "content": "是的，如果xx在发布会上错误地标注了xx100 Pro的芯片信息，那么向xx和用户道歉是合适的。这种错误可能会对xx品牌和用户造成困扰和误解，因此公开道歉并纠正错误是一个负责任的行为。同时，这也展示了xx对于准确性和专业性的重视，有助于维护品牌形象和信誉。"},{"role": "user", "content": "今天xx有道歉吗"}]

必选

显示子属性 隐藏子属性

 role string

角色设定，可选值包括user、assistant user：用户 assistant：模型

必选

 content string

content为文本时, 对应对话内容，即用户query问题，说明： 不能为空。 多轮对话中，用户最后一次输入message对应的content不能为空字符，如空格、"\n"、“\r”、“\f”等。

必选

 stream boolean

是否为流式请求。值含义： true：使用HTTP SSE流式响应 false：以非流式结果返回 默认值为false；

可选

 resource_type_filter object {2}

支持设置网页、视频、图片搜索模态，网页top_k最大取值为50，视频top_k最大为10，图片top_k最大为30，默认值为： [{"type": "web","top_k": 20}，{"type": "video","top_k": 0}，{"type": "image","top_k": 0}]

可选

显示子属性 隐藏子属性

 type string

可选值：video、image、web video: 视频 image: 图片 web：网页

必选

 top_k integer

指定模态最大返回个数

必选

 search_filter object {2}

定义检索过滤条件，search_source为baidu_search_v1时后置站点过滤， 当search_source为baidu_search_v2时为指定站点搜索

可选

显示子属性 隐藏子属性

 match object {1}

条件查询。

可选

显示子属性 隐藏子属性

 site array

支持设置指定站点的搜索条件，即仅在设置的站点中进行内容搜索，仅对网页、视频结果生效。目前支持设置100个站点。示例：["tieba.baidu.com","baike.baidu.com"] 注意：此为付费功能，目前限时免费中

可选

显示子属性 隐藏子属性

 items string

 range object {1}

范围查询

可选

显示子属性 隐藏子属性

 page_time object {4}

假设下述的now时间是2024-07-16。

可选

显示子属性 隐藏子属性

 gte string

时间查询参数，大于或等于。"now-1w/d"，2024-07-16前一周、向下做舍入，即大于2024-07-09 00:00:00，包含2024-07-09完整天。

可选

 gt string

时间查询参数，大于。"now-1w/d"，2024-07-16前一周、向上做舍入，即大于2024-07-09 23:59:59，不包含2024-07-09完整天。

可选

 lte string

时间查询参数，小于或等于。"now-1w/d"，2024-07-16前一周、向上做舍入，即小于2024-07-09 23:59:59，包含2024-07-09完整天。

可选

 lt string

时间查询参数，小于。"now-1w/d"，2024-07-16前一周、向下做舍入，即小于2024-07-09 00:00:00，不包含2024-07-09完整天。

可选

 temperature float

模型采样参数。较高的数值会使输出更加随机，而较低的数值会使其更加集中和确定 值范围：(0, 1] 默认值：1e-6 注意：该值越大，模型输出越多样，也越不稳定

可选

 top_p float

模型采样参数。影响输出文本的多样性，取值越大，生成文本的多样性越强 值范围：(0, 1] 默认值：1e-10 注意：该值越大，模型输出越多样，也越不稳定

可选

 response_format object {2}

默认文本输出

可选

显示子属性 隐藏子属性

 type string

输出格式类型，可选值：text、json_object、json_schema，默认值text；

必选

 json_schema object {0}

当 type 为 json_schema 时，必填；详细信息请参考[协议文档](https://json-schema.org/overview/what-is-jsonschema)

可选

显示子属性 隐藏子属性

暂无参数

 model string

是否开启思考能力，枚举值：thinking, auto_thinking, non_thinking。  
 默认值：non_thinking  
 枚举值及含义：  
 thinking: 智能总结开启模型思考能力，使用思考模型。限时免费中  
 auto_thinking: 根据query自动判断是否需要思考，自适应开启思考能力  
 non_thinking: 智能总结不开启模型思考能力，使用非思考模型

可选

## 示例代码[](https://cloud.baidu.com/doc/qianfan-api/s/wmjqtqr7w#%E7%A4%BA%E4%BE%8B%E4%BB%A3%E7%A0%81)

请求示例

 复制 

```
```
curl --location 'https://qianfan.baidubce.com/v2/ai_search/web_summary' \
--header 'Authorization: Bearer <API Key\>' 
--header 'X-Appbuilder-Request-Id: a728c65f-840a-4769-a37f-5639a1ad8b1f' \
--header 'X-Appbuilder-User-Id: f96e262041644ce2a0670bdc57f3cd7b' \
--header 'Content-Type: application/json' \
--data '{"messages": [{"role": "user", "content": "北戴河景区"}],
"stream": true}'
```
```

## 返回响应[](https://cloud.baidu.com/doc/qianfan-api/s/wmjqtqr7w#%E8%BF%94%E5%9B%9E%E5%93%8D%E5%BA%94)

Headers 参数

除公共头域外，无其它特殊头域

返回参数

 request_id string

请求ID

可选

 code string

错误代码，当发生异常时返回

可选

 message string

错误消息，当发生异常时返回

可选

 choices object {2}

模型生成的 completion 的选择列表

可选

显示子属性 隐藏子属性

 message object {2}

非流式模型生成的completion消息

可选

显示子属性 隐藏子属性

 content string

completion内容

可选

 role string

固定值assistant

可选

 delta object {2}

流式返回的completion增量

可选

显示子属性 隐藏子属性

 content string

completion内容

可选

 role string

固定值assistant

可选

 references object {15}

模型回答参考引用内容

可选

显示子属性 隐藏子属性

 icon string

站点图标

可选

 id integer

网页编号1、2、3

可选

 title string

网页标题

可选

 url string

网页地址

可选

 content string

当enable_full_content设为true时，该字段为网页内容全文；当enable_full_content设为false时，为网页内容摘要，此时与snippet字段内容相同。

可选

 date string

网页日期

可选

 type string

检索资源类型： web:网页 image:图像内容 video:视频内容 aladdin:阿拉丁

可选

 website string

站点名称

可选

 image object {3}

图片详情

可选

显示子属性 隐藏子属性

 url string

图片链接

可选

 height string

图片高度

可选

 width string

图片宽度

可选

 video object {6}

视频详情

可选

显示子属性 隐藏子属性

 url string

视频链接

可选

 height string

视频高度

可选

 width string

视频宽度

可选

 size string

视频大小，单位Bytes

可选

 duration string

视频长度，单位秒

可选

 hover_pic string

视频封面图

可选

 aladdin object {0}

阿拉丁详细内容，见文档对外公布文档-[阿拉丁卡结构化信息（beta）](https://cloud.baidu.com/doc/qianfan-api/s/Xmjsa5ct9)

可选

显示子属性 隐藏子属性

暂无参数

 snippet string

网页内容摘要（非网页内容原文）

可选

 web_extensions object {1}

网页相关图片

可选

显示子属性 隐藏子属性

 images object {3}

网页相关图片

可选

显示子属性 隐藏子属性

 images[0].url string

图片链接

可选

 images[0].height string

图片高度

可选

 images[0].width string

图片宽度

可选

 rerank_score float

网页、视频、图片相关性得分，取值范围0～1

可选

 authority_score float

网页权威性评分，取值范围0～1

可选

响应示例

 复制 

```
```
{"request_id":"a728c65f-840a-4769-a37f-5639a1ad8b1f","choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"北戴河景区位于河北省秦皇岛市西南部，南临渤海，北靠联峰山，地处燕山余脉与渤海交汇地带，是华北地区著名的滨海旅游与避暑胜地。作为中国四大避暑地之一，北戴河景区不仅自然风光秀美，而且历史文化底蕴深厚，兼具生态价值与旅游功能。\n\n### 一、地理与规划概况\n\n| 属性 | 信息 |\n|------|------|\n| 地理位置 | 河北省秦皇岛市西南部，南临渤海，北靠联峰山，东接辽宁，西连京津 |\n| 地理范围 | 地跨秦皇岛市四区三县，规划总面积约 **365.97 平方千米** |\n| 地形地貌 | 以海滨平原和低山丘陵为主，地质结构稳定，拥有典型海蚀地貌 |\n| 气候类型 | 暖温带半湿润大陆性季风气候，夏季凉爽宜人，年均气温约12℃ |\n\n\u003e **信息来源**：网页2、网页3、网页4\n\n---\n\n### 二、核心景区构成与功能分区\n\n北戴河景区属于**分散型风景区**，由六大特色景区构成，按地理方位自北向南划分为五大功能区域：\n\n1. **北部山林区域**：以联峰山为核心，植被茂密，为城市绿肺与生态屏障。\n2. **低山丘陵区域**：兼具自然景观与人文遗迹，如鸽子窝公园、老虎石公园等。\n3. **山间盆地区域**：地形相对封闭，适宜生态保育与休闲康养。\n4. **冲积平原区域**：地势平坦，是城市建设和农业活动的主要区域。\n5. **东部沿海区域**：拥有长达二十里的优质沙滩，是海滨度假的核心地带。\n\n**六大具体景区**包括：\n- 北戴河海滨风景区（核心）\n- 山海关（历史名城，长城起点）\n- 南戴河（以“海上乐园”著称）\n- 黄金海岸（国家级海洋公园）\n- 祖山（燕山山脉重要支脉，自然生态保护区）\n- 碣石山（古代帝王巡游之地，文化底蕴深厚）\n\n\u003e **信息来源**：网页2、网页3\n\n---\n\n### 三、生态与环境价值\n\n北戴河不仅是旅游胜地，更是重要的生态节点。其周边生态系统包括：\n- **滨海湿地系统**：如七里海潟湖，是东亚—澳大利西亚候鸟迁徙通道的关键中转站。\n- **海洋碳汇功能**：通过退养还湿、微地形改造、岸线修复等措施，七里海潟湖水面面积已恢复至2015年的**3倍**，显著提升区域碳汇能力。\n- **灾害预警体系**：已构建“空—天—地—海”一体化海洋灾害监测预警系统，增强防灾减灾能力。\n\n\u003e **信息来源**：网页1\n\n---\n\n### 四、旅游与文化地位\n\n北戴河景区享有极高声誉，曾获多项国家级荣誉：\n- 首批国家级重点风景名胜区\n- 首批全国旅游示范区\n- 中国优秀旅游城市\n- 全国文明城市\n- 国家森林城市\n\n同时，北戴河地处“京津冀黄金旅游圈”核心节点，与北京、天津、承德共同构成区域旅游联动网络，是国内外游客理想的休闲度假目的地。\n\n---\n\n### 五、未来发展方向\n\n随着生态文明建设深入推进，北戴河景区正从传统观光型向**生态旅游+智慧管理+可持续发展**转型：\n- 推进生态修复工程（如七里海潟湖恢复项目）\n- 强化智慧化监测与预警系统建设\n- 发展低碳旅游与绿色交通体系\n- 深化文化遗产保护与活化利用\n\n---\n\n### 总结\n\n北戴河景区集自然之美、历史之韵、生态之重于一体，既是避暑胜地，也是生态屏障与文化地标。其在地理区位、生态功能、旅游价值与政策支持方面均具备显著优势，未来将持续发挥京津冀协同发展中的重要支点作用。\n\n如需了解具体景区开放时间、门票信息或交通指南，可进一步查阅官方旅游平台或景区公告。"}}],"references":[{"id":1,"url":"https://i.ifeng.com/c/8oU2F1wG30G","title":"万鸟归来 七里海潟湖十年重生","date":"2025-10-12 00:00:00","content":"七里海潟湖位于秦皇岛市北戴河新区,是华北地区最大的潟湖、东亚—澳大利西亚候鸟迁徙通道的重要节点,也是我省提升海洋碳汇能力、增强海洋防灾减灾功能的重要海洋生态系统。 通过协议退养还湿、微地形改造、岸线修复等生态减灾修复措施,目前七里海潟湖水面面积恢复至2015年的3倍,同时构建起“空—天—地—海”一体化海洋灾害预警监测体系,区域生态功能得到改善,防灾减灾能力有效提升。 退养还湿 水面面积扩大至十年前的3倍 10月20日,秦皇岛市北戴河新区秋高气爽。","icon":"http://x0.ifengimg.com/fe/custom/ifeng.f52bd6.png","web_anchor":"","type":"web","website":"凤凰网","video":null,"image":null,"is_aladdin":false,"aladdin":null,"snippet":"七里海潟湖位于秦皇岛市北戴河新区,是华北地区最大的潟湖、东亚—澳大利西亚候鸟迁徙通道的重要节点,也是我省提升海洋碳汇能力、增强海洋防灾减灾功能的重要海洋生态系统。 通过协议退养还湿、微地形改造、岸线修复等生态减灾修复措施,目前七里海潟湖水面面积恢复至2015年的3倍,同时构建起“空—天—地—海”一体化海洋灾害预警监测体系,区域生态功能得到改善,防灾减灾能力有效提升。 退养还湿 水面面积扩大至十年前的3倍 10月20日,秦皇岛市北戴河新区秋高气爽。","web_extensions":{"images":null},"rerank_score":1,"authority_score":0.5},{"id":2,"url":"https://baike.baidu.com/item/北戴河景区/10433529","title":"北戴河景区","date":"2025-10-23 11:06:41","content":" 北戴河景区,位于河北省秦皇岛市西南部,南临渤海,北靠联峰山,东临辽宁、西接京津,北枕燕山,地跨秦皇岛市的四区三县,规划总面积约为365.97平方千米。 [3] [6] [16] 北戴河景区的地形地貌以海滨平原和丘陵为主,地质结构稳定,拥有多处海蚀地貌。水文特征显著,毗邻渤海,海岸线绵长,海水清澈。气候类型为暖温带半湿润大陆性季风气候。植被类型包括温带落叶阔叶林及沿海盐生植被。生物资源包括多种海洋生物和内陆野生动物。北戴河景区属于分散型风景区,包含六大特色景区。景区由北向南划分为五大区域:北部山林区域、低山丘陵区域、山间盆地区域、冲积平原区域和东部沿海区域。景区还包括山海关、北戴河、南戴河、黄金海岸、祖山和碣石山六大具体景区。 [7] 北戴河景区是中国四大避暑地之一,先后被评为首批国家级重点风景名胜区、首批全国旅游示范区、中国优秀旅游城市,荣获全国文明城市、国家森林城市桂冠。","icon":"https://mbs1.bdstatic.com/searchbox/mappconsole/image/20200630/db4d874a-872b-4b27-931d-775a91ed0003.png","web_anchor":"","type":"web","website":"百度百科","video":null,"image":null,"is_aladdin":true,"aladdin":null,"snippet":" 北戴河景区,位于河北省秦皇岛市西南部,南临渤海,北靠联峰山,东临辽宁、西接京津,北枕燕山,地跨秦皇岛市的四区三县,规划总面积约为365.97平方千米。 [3] [6] [16] 北戴河景区的地形地貌以海滨平原和丘陵为主,地质结构稳定,拥有多处海蚀地貌。水文特征显著,毗邻渤海,海岸线绵长,海水清澈。气候类型为暖温带半湿润大陆性季风气候。植被类型包括温带落叶阔叶林及沿海盐生植被。生物资源包括多种海洋生物和内陆野生动物。北戴河景区属于分散型风景区,包含六大特色景区。景区由北向南划分为五大区域:北部山林区域、低山丘陵区域、山间盆地区域、冲积平原区域和东部沿海区域。景区还包括山海关、北戴河、南戴河、黄金海岸、祖山和碣石山六大具体景区。 [7] 北戴河景区是中国四大避暑地之一,先后被评为首批国家级重点风景名胜区、首批全国旅游示范区、中国优秀旅游城市,荣获全国文明城市、国家森林城市桂冠。","web_extensions":{"images":[{"url":"https://bkimg.cdn.bcebos.com/pic/2934349b033b5bb5ab25ff723cd3d539b700bc48","height":"450","width":"600"},{"url":"https://bkimg.cdn.bcebos.com/pic/08f790529822720e9dda7f477dcb0a46f21fab73","height":"492","width":"779"},{"url":"https://bkimg.cdn.bcebos.com/pic/f29faa8fe1e485aaf11f3651","height":"274","width":"400"},{"url":"https://bkimg.cdn.bcebos.com/pic/3812b31bb051f8196d4316fbdab44aed2e73e719","height":"600","width":"800"},{"url":"https://bkimg.cdn.bcebos.com/pic/0d729944ce3d0b08500ffe2e","height":"329","width":"453"}]},"rerank_score":1,"authority_score":1},{"id":3,"url":"https://baike.baidu.com/item/北戴河风景名胜区/6749014","title":"北戴河风景名胜区","date":"2025-10-21 16:29:05","content":" 北戴河风景名胜区因为它拥有避暑胜地北戴河、历史名城山海关和天然不冻良港而驰名天下。 秦皇岛北戴河风景名胜区位于渤海之滨,东临辽宁、西接京津,北枕燕山,地跨秦皇岛市的四区三县,规划总面积约为365.97平方公里,是我国第一批国家重点风景名胜区之一。 北戴河风景名胜区位于河北省秦皇岛市西南,南临渤海,北靠联峰山。","icon":"https://mbs1.bdstatic.com/searchbox/mappconsole/image/20200630/db4d874a-872b-4b27-931d-775a91ed0003.png","web_anchor":"","type":"web","website":"百度百科","video":null,"image":null,"is_aladdin":true,"aladdin":null,"snippet":" 北戴河风景名胜区因为它拥有避暑胜地北戴河、历史名城山海关和天然不冻良港而驰名天下。 秦皇岛北戴河风景名胜区位于渤海之滨,东临辽宁、西接京津,北枕燕山,地跨秦皇岛市的四区三县,规划总面积约为365.97平方公里,是我国第一批国家重点风景名胜区之一。 北戴河风景名胜区位于河北省秦皇岛市西南,南临渤海,北靠联峰山。","web_extensions":{"images":[{"url":"https://bkimg.cdn.bcebos.com/pic/562c11dfa9ec8a131b0ac69cf903918fa0ecc0be","height":"0","width":"0"},{"url":"https://bkimg.cdn.bcebos.com/pic/d8f9d72a6059252d009a5041319b033b5ab5b9e2","height":"0","width":"0"},{"url":"https://bkimg.cdn.bcebos.com/pic/4ec2d5628535e5dd8ebf8f6e76c6a7efcf1b62eb","height":"0","width":"0"},{"url":"https://bkimg.cdn.bcebos.com/pic/42166d224f4a20a47817f53f90529822720ed039","height":"0","width":"0"},{"url":"https://bkimg.cdn.bcebos.com/pic/d01373f082025aaf51f2b033fbedab64024f1a02","height":"0","width":"0"}]},"rerank_score":1,"authority_score":1},{"id":4,"url":"https://baike.baidu.com/item/北戴河海滨风景区/3233396","title":"北戴河海滨风景区","date":"2025-03-04 15:08:06","content":" 北戴河海滨风景区地处河北省秦皇岛市中心的西部。是秦皇岛的城市区之一,气候宜人,二十里长、曲折平坦的沙质海滩,沙软潮平,背靠树木葱郁的联峰山,自然环境优美。与北京、天津、承德共同构成京津冀黄金旅游圈,北戴河处于旅游圈的重要节点地位。北戴河海滨风景区,中国著名海滨避暑胜地,拥有优质海滩、丰富自然与人文景观,适合休闲度假、观海赏日及体验渔家生活。 南京汤山温泉旅游度假区 南京汤山温泉旅游度假区位于南京市江宁区东部,区域面积29.74平方公里,2007年启动汤山新城建设,2012年","icon":"https://mbs1.bdstatic.com/searchbox/mappconsole/image/20200630/db4d874a-872b-4b27-931d-775a91ed0003.png","web_anchor":"","type":"web","website":"百度百科","video":null,"image":null,"is_aladdin":true,"aladdin":null,"snippet":" 北戴河海滨风景区地处河北省秦皇岛市中心的西部。是秦皇岛的城市区之一,气候宜人,二十里长、曲折平坦的沙质海滩,沙软潮平,背靠树木葱郁的联峰山,自然环境优美。与北京、天津、承德共同构成京津冀黄金旅游圈,北戴河处于旅游圈的重要节点地位。北戴河海滨风景区,中国著名海滨避暑胜地,拥有优质海滩、丰富自然与人文景观,适合休闲度假、观海赏日及体验渔家生活。 南京汤山温泉旅游度假区 南京汤山温泉旅游度假区位于南京市江宁区东部,区域面积29.74平方公里,2007年启动汤山新城建设,2012年","web_extensions":{"images":null},"rerank_score":1,"authority_score":1}]}
```
<br>

#### 流式
```
data: {"request_id":"a728c65f-840a-4769-a37f-5639a1ad8b1f","choices":null,"references":[{"id":1,"url":"https://i.ifeng.com/c/8oU2F1wG30G","title":"万鸟归来 七里海潟湖十年重生","date":"2025-10-12 00:00:00","content":"七里海潟湖位于秦皇岛市北戴河新区,是华北地区最大的潟湖、东亚—澳大利西亚候鸟迁徙通道的重要节点,也是我省提升海洋碳汇能力、增强海洋防灾减灾功能的重要海洋生态系统。 通过协议退养还湿、微地形改造、岸线修复等生态减灾修复措施,目前七里海潟湖水面面积恢复至2015年的3倍,同时构建起“空—天—地—海”一体化海洋灾害预警监测体系,区域生态功能得到改善,防灾减灾能力有效提升。 退养还湿 水面面积扩大至十年前的3倍 10月20日,秦皇岛市北戴河新区秋高气爽。","icon":"http://x0.ifengimg.com/fe/custom/ifeng.f52bd6.png","web_anchor":"","type":"web","website":"凤凰网","video":null,"image":null,"is_aladdin":false,"aladdin":null,"snippet":"七里海潟湖位于秦皇岛市北戴河新区,是华北地区最大的潟湖、东亚—澳大利西亚候鸟迁徙通道的重要节点,也是我省提升海洋碳汇能力、增强海洋防灾减灾功能的重要海洋生态系统。 通过协议退养还湿、微地形改造、岸线修复等生态减灾修复措施,目前七里海潟湖水面面积恢复至2015年的3倍,同时构建起“空—天—地—海”一体化海洋灾害预警监测体系,区域生态功能得到改善,防灾减灾能力有效提升。 退养还湿 水面面积扩大至十年前的3倍 10月20日,秦皇岛市北戴河新区秋高气爽。","web_extensions":{"images":null},"rerank_score":1,"authority_score":0.5},{"id":2,"url":"https://baike.baidu.com/item/北戴河景区/10433529","title":"北戴河景区","date":"2025-10-23 11:06:41","content":" 北戴河景区,位于河北省秦皇岛市西南部,南临渤海,北靠联峰山,东临辽宁、西接京津,北枕燕山,地跨秦皇岛市的四区三县,规划总面积约为365.97平方千米。 [3] [6] [16] 北戴河景区的地形地貌以海滨平原和丘陵为主,地质结构稳定,拥有多处海蚀地貌。水文特征显著,毗邻渤海,海岸线绵长,海水清澈。气候类型为暖温带半湿润大陆性季风气候。植被类型包括温带落叶阔叶林及沿海盐生植被。生物资源包括多种海洋生物和内陆野生动物。北戴河景区属于分散型风景区,包含六大特色景区。景区由北向南划分为五大区域:北部山林区域、低山丘陵区域、山间盆地区域、冲积平原区域和东部沿海区域。景区还包括山海关、北戴河、南戴河、黄金海岸、祖山和碣石山六大具体景区。 [7] 北戴河景区是中国四大避暑地之一,先后被评为首批国家级重点风景名胜区、首批全国旅游示范区、中国优秀旅游城市,荣获全国文明城市、国家森林城市桂冠。","icon":"https://mbs1.bdstatic.com/searchbox/mappconsole/image/20200630/db4d874a-872b-4b27-931d-775a91ed0003.png","web_anchor":"","type":"web","website":"百度百科","video":null,"image":null,"is_aladdin":true,"aladdin":null,"snippet":" 北戴河景区,位于河北省秦皇岛市西南部,南临渤海,北靠联峰山,东临辽宁、西接京津,北枕燕山,地跨秦皇岛市的四区三县,规划总面积约为365.97平方千米。 [3] [6] [16] 北戴河景区的地形地貌以海滨平原和丘陵为主,地质结构稳定,拥有多处海蚀地貌。水文特征显著,毗邻渤海,海岸线绵长,海水清澈。气候类型为暖温带半湿润大陆性季风气候。植被类型包括温带落叶阔叶林及沿海盐生植被。生物资源包括多种海洋生物和内陆野生动物。北戴河景区属于分散型风景区,包含六大特色景区。景区由北向南划分为五大区域:北部山林区域、低山丘陵区域、山间盆地区域、冲积平原区域和东部沿海区域。景区还包括山海关、北戴河、南戴河、黄金海岸、祖山和碣石山六大具体景区。 [7] 北戴河景区是中国四大避暑地之一,先后被评为首批国家级重点风景名胜区、首批全国旅游示范区、中国优秀旅游城市,荣获全国文明城市、国家森林城市桂冠。","web_extensions":{"images":[{"url":"https://bkimg.cdn.bcebos.com/pic/2934349b033b5bb5ab25ff723cd3d539b700bc48","height":"450","width":"600"},{"url":"https://bkimg.cdn.bcebos.com/pic/08f790529822720e9dda7f477dcb0a46f21fab73","height":"492","width":"779"},{"url":"https://bkimg.cdn.bcebos.com/pic/f29faa8fe1e485aaf11f3651","height":"274","width":"400"},{"url":"https://bkimg.cdn.bcebos.com/pic/3812b31bb051f8196d4316fbdab44aed2e73e719","height":"600","width":"800"},{"url":"https://bkimg.cdn.bcebos.com/pic/0d729944ce3d0b08500ffe2e","height":"329","width":"453"}]},"rerank_score":1,"authority_score":1},{"id":3,"url":"https://baike.baidu.com/item/北戴河风景名胜区/6749014","title":"北戴河风景名胜区","date":"2025-10-21 16:29:05","content":" 北戴河风景名胜区因为它拥有避暑胜地北戴河、历史名城山海关和天然不冻良港而驰名天下。 秦皇岛北戴河风景名胜区位于渤海之滨,东临辽宁、西接京津,北枕燕山,地跨秦皇岛市的四区三县,规划总面积约为365.97平方公里,是我国第一批国家重点风景名胜区之一。 北戴河风景名胜区位于河北省秦皇岛市西南,南临渤海,北靠联峰山。","icon":"https://mbs1.bdstatic.com/searchbox/mappconsole/image/20200630/db4d874a-872b-4b27-931d-775a91ed0003.png","web_anchor":"","type":"web","website":"百度百科","video":null,"image":null,"is_aladdin":true,"aladdin":null,"snippet":" 北戴河风景名胜区因为它拥有避暑胜地北戴河、历史名城山海关和天然不冻良港而驰名天下。 秦皇岛北戴河风景名胜区位于渤海之滨,东临辽宁、西接京津,北枕燕山,地跨秦皇岛市的四区三县,规划总面积约为365.97平方公里,是我国第一批国家重点风景名胜区之一。 北戴河风景名胜区位于河北省秦皇岛市西南,南临渤海,北靠联峰山。","web_extensions":{"images":[{"url":"https://bkimg.cdn.bcebos.com/pic/562c11dfa9ec8a131b0ac69cf903918fa0ecc0be","height":"0","width":"0"},{"url":"https://bkimg.cdn.bcebos.com/pic/d8f9d72a6059252d009a5041319b033b5ab5b9e2","height":"0","width":"0"},{"url":"https://bkimg.cdn.bcebos.com/pic/4ec2d5628535e5dd8ebf8f6e76c6a7efcf1b62eb","height":"0","width":"0"},{"url":"https://bkimg.cdn.bcebos.com/pic/42166d224f4a20a47817f53f90529822720ed039","height":"0","width":"0"},{"url":"https://bkimg.cdn.bcebos.com/pic/d01373f082025aaf51f2b033fbedab64024f1a02","height":"0","width":"0"}]},"rerank_score":1,"authority_score":1},{"id":4,"url":"https://baike.baidu.com/item/北戴河海滨风景区/3233396","title":"北戴河海滨风景区","date":"2025-03-04 15:08:06","content":" 北戴河海滨风景区地处河北省秦皇岛市中心的西部。是秦皇岛的城市区之一,气候宜人,二十里长、曲折平坦的沙质海滩,沙软潮平,背靠树木葱郁的联峰山,自然环境优美。与北京、天津、承德共同构成京津冀黄金旅游圈,北戴河处于旅游圈的重要节点地位。北戴河海滨风景区,中国著名海滨避暑胜地,拥有优质海滩、丰富自然与人文景观,适合休闲度假、观海赏日及体验渔家生活。 南京汤山温泉旅游度假区 南京汤山温泉旅游度假区位于南京市江宁区东部,区域面积29.74平方公里,2007年启动汤山新城建设,2012年","icon":"https://mbs1.bdstatic.com/searchbox/mappconsole/image/20200630/db4d874a-872b-4b27-931d-775a91ed0003.png","web_anchor":"","type":"web","website":"百度百科","video":null,"image":null,"is_aladdin":true,"aladdin":null,"snippet":" 北戴河海滨风景区地处河北省秦皇岛市中心的西部。是秦皇岛的城市区之一,气候宜人,二十里长、曲折平坦的沙质海滩,沙软潮平,背靠树木葱郁的联峰山,自然环境优美。与北京、天津、承德共同构成京津冀黄金旅游圈,北戴河处于旅游圈的重要节点地位。北戴河海滨风景区,中国著名海滨避暑胜地,拥有优质海滩、丰富自然与人文景观,适合休闲度假、观海赏日及体验渔家生活。 南京汤山温泉旅游度假区 南京汤山温泉旅游度假区位于南京市江宁区东部,区域面积29.74平方公里,2007年启动汤山新城建设,2012年","web_extensions":{"images":null},"rerank_score":1,"authority_score":1}]}

data: {"request_id":"a728c65f-840a-4769-a37f-5639a1ad8b1f","choices":[{"finish_reason":"","delta":{"role":"assistant","content":"北"}}]}

data: {"request_id":"a728c65f-840a-4769-a37f-5639a1ad8b1f","choices":[{"finish_reason":"","delta":{"role":"","content":"戴"}}]}

data: {"request_id":"a728c65f-840a-4769-a37f-5639a1ad8b1f","choices":[{"finish_reason":"","delta":{"role":"","content":"河"}}]}

data: {"request_id":"a728c65f-840a-4769-a37f-5639a1ad8b1f","choices":[{"finish_reason":"","delta":{"role":"","content":"景区"}}]}

...
```
```

