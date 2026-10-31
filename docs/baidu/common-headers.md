> Source: https://cloud.baidu.com/doc/qianfan-api/s/3m9b5lqft
> Retrieved: 2026-10-31
> Covers: Qianfan API common conventions: public request headers (Authorization: Bearer <API Key>), response structure

# 通用说明

更新时间：2025-04-18

## API认证机制[](https://cloud.baidu.com/doc/qianfan-api/s/3m9b5lqft#api%E8%AE%A4%E8%AF%81%E6%9C%BA%E5%88%B6)

使用API Key调用模型 API流程，请参考[认证鉴权](https://cloud.baidu.com/doc/qianfan-api/s/ym9chdsy5)。

## 通信协议[](https://cloud.baidu.com/doc/qianfan-api/s/3m9b5lqft#%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE)

API 调用遵循 HTTPS 协议。

## 请求结构说明[](https://cloud.baidu.com/doc/qianfan-api/s/3m9b5lqft#%E8%AF%B7%E6%B1%82%E7%BB%93%E6%9E%84%E8%AF%B4%E6%98%8E)

数据交换格式为JSON，所有request/response body内容均采用UTF-8编码。

请求参数包括如下：

| 参数类型 | 说明 |
| --- | --- |
| HEADER | 通过HTTP头域传入，如:x-bce-date |
| Query参数 | URL中携带的请求参数 |
| RequestBody | 通过JSON格式组织的请求数据体 |

## 响应结构说明[](https://cloud.baidu.com/doc/qianfan-api/s/3m9b5lqft#%E5%93%8D%E5%BA%94%E7%BB%93%E6%9E%84%E8%AF%B4%E6%98%8E)

| 响应内容 | 说明 |
| --- | --- |
| HTTP STATUS CODE | 如200，400，403，404等 |
| ResponseBody | 通过JSON格式组织的响应数据体 |

## 公共请求头与公共响应头[](https://cloud.baidu.com/doc/qianfan-api/s/3m9b5lqft#%E5%85%AC%E5%85%B1%E8%AF%B7%E6%B1%82%E5%A4%B4%E4%B8%8E%E5%85%AC%E5%85%B1%E5%93%8D%E5%BA%94%E5%A4%B4)

### 公共请求头[](https://cloud.baidu.com/doc/qianfan-api/s/3m9b5lqft#%E5%85%AC%E5%85%B1%E8%AF%B7%E6%B1%82%E5%A4%B4)

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| Content-Type | string | 是 | 固定值application/json |
| Authorization | string | 是 | 用于验证请求合法性的认证信息，说明： （1）该字段值，需通过字符串`Bearer`和 `API Key`值拼接组成，示例值如`Bearer bce-v3/ALTAK-*********/614fb**********` （2）通过在[控制台-系统管理与统计-API Key管理](https://console.bce.baidu.com/iam/#/iam/apikey/list)页面，创建并获取API Key，该值永久有效 |
| appid | string | 否 | V2版本接口对应的应用ID，说明： （1）可以通过[控制台-系统管理与统计-应用接入](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)页面，在应用列表查看应用ID，如下图所示： （2）如果无应用，需要先创建V2版本服务对应的应用，在[控制台-系统管理与统计-应用接入](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)页面创建应用。 |
| X-Request-Id | string | 否 | 用户入参 X-Request-Id，则返回的 X-Request-Id 头是用户的入参值 |

### 公共响应头[](https://cloud.baidu.com/doc/qianfan-api/s/3m9b5lqft#%E5%85%AC%E5%85%B1%E5%93%8D%E5%BA%94%E5%A4%B4)

| 头域 | 说明 |
| --- | --- |
| Content-Type | 在返回结果是JSON时，为application/json; charset=utf-8 |
| X-Request-Id | 对应请求的requestId |

