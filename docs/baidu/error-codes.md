> Source: https://cloud.baidu.com/doc/qianfan-api/s/Om9b4yj3w
> Retrieved: 2026-10-31
> Covers: Qianfan API error format and error codes (incl. 429 rate limits)

# 错误码

更新时间：2026-03-31

## 错误码说明[](https://cloud.baidu.com/doc/qianfan-api/s/Om9b4yj3w#%E9%94%99%E8%AF%AF%E7%A0%81%E8%AF%B4%E6%98%8E)

本文主要介绍模型对应的错误码及其错误描述。在调用API请求后，可以通过返回的错误码、错误信息及排查建议等进行问题排查。

## 错误码格式[](https://cloud.baidu.com/doc/qianfan-api/s/Om9b4yj3w#%E9%94%99%E8%AF%AF%E7%A0%81%E6%A0%BC%E5%BC%8F)

若请求错误，服务器将以JSON格式返回错误信息，错误信息包含：

| 参数名 | 类型 | 说明 |
| --- | --- | --- |
| code | String | 错误码 |
| message | String | 错误描述信息，帮助理解和解决发生的错误。 |
| type | String | 错误描述类型 |

  

JSON 复制 

```
1{
2    "error":
3        {
4            "code":"malformed_json",
5            "message":"Invalid Argument",
6            "type":"invalid_request_error"
7        },
8    "id":"as-****xi6mm8"
9}
```

## 错误码列表[](https://cloud.baidu.com/doc/qianfan-api/s/Om9b4yj3w#%E9%94%99%E8%AF%AF%E7%A0%81%E5%88%97%E8%A1%A8)

| HTTP状态码 | 类型 | 错误码 | 错误信息 | 说明 |
| --- | --- | --- | --- | --- |
| 400 | invalid_request_error | malformed_json | Invalid Argument | 入参格式有误，不是标准json格式 |
| 400 | invalid_request_error | invalid_model | model is empty | 未指定model参数 |
| 400 | invalid_request_error | invalid_messages | 返回的具体错误信息 | message格式不符合规范，message中有详细说明 |
| 400 | invalid_request_error | characters_too_long | the max input characters is xxx | 请求长度不能超过最大字符限制，即用户输入大模型内容过长，可以尝试以下方法解决： · 适当缩短输入 |
| 400 | invalid_request_error | tokens_too_long | Prompt tokens too long | 【用户输入错误】请求内容超过大模型内部限制，即用户输入大模型内容过长，可以尝试以下方法解决： · 适当缩短输入 |
| 400 | invalid_request_error | invalid_argument | 返回的具体错误信息 | 请参考返回的错误信息 |
| 400 | invalid_request_error | invalid_image_generation_prompt | prompt is invalid, please check parameter | prompt不合法 |
| 400 | invalid_request_error | invalid_image_generation_refer_image | refer image is invalid, please check parameter | 传入的参考图不合法 |
| 400 | invalid_request_error | invalid_image_url | the image width and height are not within the allowed range | 图像尺寸超出限制范围。图像尺寸范围需要小于6000px*6000px，最短边不低于5px。 |
| 400 | invalid_request_error | invalid_plugin_argument | 返回的具体错误信息 | 插件服务报错，请参考[返回的错误信息](https://cloud.baidu.com/doc/qianfan-docs/s/Am9bkjdv4#%E9%94%99%E8%AF%AF%E7%A0%81) |
| 400 | unsafe_request | image_url_unsafe | the content of image_url.url field is unsafe | image_url 内容不合法，如果仍未解决，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 401 | access_denied | no_parameter_permission | 返回的具体错误信息 | 请参考返回的错误信息 |
| 401 | invalid_request_error | invalid_model | The model does not exist or you do not have access to it. | 模型不存在或者用户没有使用这个模型的权限 |
| 401 | invalid_request_error | invalid_appid | No permission to use the appid | appid鉴权失败，该用户没有使用这个appid的权限 |
| 401 | invalid_request_error | invalid_iam_token | IAM Certification failed | iam鉴权失败，bearer token无效或过期，或者请求的Authorization没加Bearer |
| 403 | unsafe_request | system_unsafe | the content of system field is invalid | system字段内容不安全 |
| 403 | unsafe_request | user_setting_unsafe | the content of user field is invalid | user_setting内容不合法 |
| 403 | unsafe_request | functions_unsafe | the content of functions field is invalid | function内容不合法 |
| 403 | access_denied | account_overdue | Access denied due to overdue account | 账号已欠费（余额<0），如需继续调用，请前往[百度智能云财务系统](https://console.bce.baidu.com/billing/index)进行充值 |
| 403 | access_denied | model_offline | The model is offline | 请求模型已下线 |
| 405 | invalid_request_error | method_not_supported | Only POST requests are accepted | 此接口只支持POST请求 |
| 429 | rate_limit_exceeded | rpm_rate_limit_exceeded | Rate limit reached for RPM | Cloud ID下RPM超限额，可以尝试以下方式解决： · 适当控制请求频率，避免失败，请参考[默认流控](https://cloud.baidu.com/doc/qianfan-docs/s/7m95lyy43) · 如果您需要提升更大的RPM/TPM配额，请在控制台上进行TPM/RPM配额的购买 · 如果仍未解决，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 429 | rate_limit_exceeded | tpm_rate_limit_exceeded | Rate limit reached for TPM | Cloud ID下TPM超限额，可以尝试以下方式解决： · 适当控制请求频率，避免失败，请参考[默认流控](https://cloud.baidu.com/doc/qianfan-docs/s/7m95lyy43) · 如果您需要提升更大的RPM/TPM配额，请在控制台上进行TPM/RPM配额的购买 · 如果仍未解决，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 429 | rate_limit_exceeded | input_tpm_rate_limit_exceeded | Rate limit reached for Input TPM | Cloud ID下输入TPM超限额，可以尝试以下方式解决： · 适当控制请求频率，避免失败，请参考[默认流控](https://cloud.baidu.com/doc/qianfan-docs/s/7m95lyy43) · 如果您需要提升更大的RPM/TPM配额，请在控制台上进行TPM/RPM配额的购买 · 如果仍未解决，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 429 | rate_limit_exceeded | output_tpm_rate_limit_exceeded | Rate limit reached for Output TPM | Cloud ID下输出TPM超限额，可以尝试以下方式解决： · 适当控制请求频率，避免失败，请参考[默认流控](https://cloud.baidu.com/doc/qianfan-docs/s/7m95lyy43) · 如果您需要提升更大的RPM/TPM配额，请在控制台上进行TPM/RPM配额的购买 · 如果仍未解决，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 429 | rate_limit_exceeded | Offline_batch_reasoning_refused | Rate limit reached for offline batch reasoning | 批推流量被拒绝，请稍后重试，如果持续出现此类错误，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 429 | rate_limit_exceeded | preemptible_rate_limit_exceeded | Rate limit reached for preemptible resource | 混抢资源qps超限，包含可抢占接口、离线推理、离线评估请求 |
| 429 | rate_limit_exceeded | user_rate_limit_exceeded | qps request limit by APP ID reached | 【用户配额超限】QPS超限额，可以尝试通过以下方法解决： · 适当控制请求频率，避免失败 · 如果仍未解决，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 429 | rate_limit_exceeded | cluster_rate_limit_exceeded | request limit by resouce cluster reached | 集群QPS超限额，请再次请求，如果持续出现此类错误，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 429 | rate_limit_exceeded | cluster_rpm_rate_limit_exceeded | Rate limit reached for Cluster RPM | 集群RPM超限额，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 429 | rate_limit_exceeded | cluster_tpm_rate_limit_exceeded | Rate limit reached for Cluster TPM | 集群TPM超限额，请在百度云控制台内[提交工单](https://console.bce.baidu.com/ticket/#/ticket/create?productId=279)反馈 |
| 500 | Internal_error | internal_error | Internal error | 【系统内部错误】服务内部错误，请稍后重试 |
| 500 | Internal_error | dispatch_internal_error | Internal error | 【系统内部错误】服务内部错误，请稍后重试 |
| 500 | Internal_error | image_generation_interal_error | image generation service interal error | 文生图服务内部错误 |

  

## Coding Plan 相关错误码[](https://cloud.baidu.com/doc/qianfan-api/s/Om9b4yj3w#coding-plan-%E7%9B%B8%E5%85%B3%E9%94%99%E8%AF%AF%E7%A0%81)

  

| HTTP状态码 | 类型 | 错误码 | 错误信息 | 说明 |
| --- | --- | --- | --- | --- |
| 401 | invalid_request_error | coding_plan_api_key_required | Coding Plan requires a dedicated API key | 当前请求未使用 Coding Plan 专属 API Key，仅可使用专属 API Key 调用 Coding Plan 套餐。 |
| 401 | invalid_request_error | coding_plan_api_key_not_allowed | Coding Plan API key is not allowed for non-Coding Plan requests | 当前使用的 Coding Plan 专属 API Key 无法调用非 Coding Plan 套餐相关接口。 |
| 403 | access_denied | coding_plan_not_subscribed | Coding Plan subscription is missing | 当前账号未订阅 Coding Plan 套餐，如需使用请前往[控制台](https://console.bce.baidu.com/qianfan/resource/subscribe)完成订阅。 |
| 403 | access_denied | coding_plan_subscription_expired | Coding Plan subscription is expired | 当前账号Coding Plan 套餐已过期，如需使用请前往[控制台](https://console.bce.baidu.com/qianfan/resource/subscribe)完成续费。 |
| 403 | access_denied | coding_plan_model_not_supported | The current model does not support Coding Plan | 当前模型不支持 Coding Plan，请切换至支持 Coding Plan 的模型后重试。 |
| 429 | quota_exceeded | coding_plan_hour_quota_exceeded | Coding Plan hour quota has been exceeded | 当前账号的 Coding Plan 5 小时调用额度已用尽，请等待额度刷新或升级套餐。 |
| 429 | quota_exceeded | coding_plan_week_quota_exceeded | Coding Plan week quota has been exceeded | 当前账号的 Coding Plan 周限额已用尽，请等待额度刷新或升级套餐。 |
| 429 | quota_exceeded | coding_plan_month_quota_exceeded | Coding Plan month quota has been exceeded | 当前账号的 Coding Plan 月限额已用尽，请等待额度刷新或升级套餐。 |
| 429 | rate_limit_exceeded | coding_plan_rate_limit_exceeded | Coding Plan request rate limit exceeded | Coding Plan 套餐请求频率过高，请稍后再试。 |
| 429 | rate_limit_exceeded | coding_plan_cluster_rate_limited | The current model is experiencing high demand | 当前模型资源紧张，请尝试使用 Coding Plan 的其他模型进行测试。 |

