> Source: https://cloud.baidu.com/doc/qianfan/s/Kmh4sutww
> Retrieved: 2026-10-31
> Covers: API Key authentication (referenced from web_summary 权限说明)

# 认证鉴权

更新时间：2025-12-24

### API Key认证机制[](https://cloud.baidu.com/doc/qianfan/s/Kmh4sutww#api-key%E8%AE%A4%E8%AF%81%E6%9C%BA%E5%88%B6)

**概述：**百度智能云推出API Key认证鉴权机制，当您通过代码调用千帆平台 OpenAPI时，需要获取API Key作为调用时的鉴权凭证。以下内容帮助您了解API Key的管控方法、认证鉴权机制、使用方式等。

**API Key 认证鉴权 ：**调用千帆平台 OpenAPI时，无需签名认证算法，易用性强，兼容国内外大模型服务的接口调用标准。前往[[API Key管理控制台]](https://console.bce.baidu.com/iam/#/iam/apikey/list)

**场景举例：**某企业通过代码调用千帆平台 OpenAPI时，可以使用API Key管控分发应用权限，比如有N个应用，开放X个应用权限给到A使用者，Y个应用权限给到B使用者。

| 功能 | API Key |
| --- | --- |
| 有效期 | 永久有效 |
| 数量上限 | 每个主账号/子用户：200个 |
| 密钥权限 | 主子用户API Key隔离，需单独配置API Key和权限，详见操作手册 |
| 如何管理 | 1、主账号直接管理所有用户的API Key； 2、子用户经授权后（授权策略：IAMReadAPIKeyPolicy、IAMManageAPIKeyPolicy），自行管理API Key |

> 策略权限说明：
> 
> 
> IAMReadAPIKeyPolicy：查看API Key列表、API Key详情、API Key明文
> 
> 
> IAMManageAPIKeyPolicy：查看API Key列表、API Key详情、API Key明文、创建API Key/Access Token、编辑API Key、删除API Key

**注意事项**

1.   请将API Key安全保存，不要与他人共享，任何发起自客户端的API调用，例如浏览器、APP或小程序等，均有可能造成API Key的泄露
2.   为API Key仅授予必要的最小调用权限
3.   建议管理员授予子用户相应的权限后（IAMReadAPIKeyPolicy、IAMManageAPIKeyPolicy），由子用户自行管理名下API Key
4.   如怀疑API Key可能已经被泄露，删除该API Key。API Key被删除后，使用该API Key的后续调用均会被拒绝

### API Key操作手册[](https://cloud.baidu.com/doc/qianfan/s/Kmh4sutww#api-key%E6%93%8D%E4%BD%9C%E6%89%8B%E5%86%8C)

当您调用千帆平台 OpenAPI时，需要获取API Key作为调用时的鉴权凭证。以下内容将帮助您了解如何创建和管理API Key

##### **子用户自行管理API Key**[](https://cloud.baidu.com/doc/qianfan/s/Kmh4sutww#%E5%AD%90%E7%94%A8%E6%88%B7%E8%87%AA%E8%A1%8C%E7%AE%A1%E7%90%86api-key)

> 若希望子用户自行管理API Key，请授权子用户：IAMManageAPIKeyPolicy，授权请参考：[子用户授权](https://cloud.baidu.com/doc/IAM/s/4jxlktzul#%E7%BB%99%E5%AD%90%E7%94%A8%E6%88%B7%E6%8E%88%E6%9D%83)

##### **创建API Key**[](https://cloud.baidu.com/doc/qianfan/s/Kmh4sutww#%E5%88%9B%E5%BB%BAapi-key)

1、访问[API Key管理控制台](https://aidpqa.qasandbox.bcetest.baidu.com/qianfan/ais/console/apiKey)

2、点击创建API Key，完成API

3、复制明文API Key后，请妥善保存

x

##### 删除API Key[](https://cloud.baidu.com/doc/qianfan/s/Kmh4sutww#%E5%88%A0%E9%99%A4api-key)

在API key列表页，点击删除，二次确认后，可将API Key删除

