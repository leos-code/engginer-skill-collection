# 用 Hurl 采集 HTTP 证据

## 执行用例

使用项目批准的测试地址和身份。每次运行创建独立的 `proof-artifacts/<运行>/<用例>/` 目录。可复跑的 Hurl 文件命名为 `request.hurl`。如果请求依赖正文文件，也保留可分享的正文文件。凭据通过 Hurl 的变量或密钥机制注入，归档文件只保留引用。

```bash
umask 077
stage_dir=$(mktemp -d)
hurl --include --no-pretty --no-color --very-verbose \
  --report-json "$stage_dir/report" \
  --output "$stage_dir/response.http" request.hurl \
  2>"$stage_dir/hurl.log"
```

`--include` 保存状态行和响应头。`--no-pretty` 保留 Hurl 收到的正文。对 HTTP 传输分帧和内容编码的检查使用相应的专用采集。正文验收可使用 `Accept-Encoding: identity`，请求本身需要验证内容编码时保留测试要求。

无效 JSON、控制字符或二进制输入需要精确字节时，把该次发送的正文写入独立文件，再在 Hurl 请求中添加 `file,request.body;`。内联多行正文可能包含结尾换行。根据实际发送的字节核对正文。

## 整理同一次交互

- 从 `hurl.log` 找到该次请求的 `>` 输出块，用发送的请求行和请求头生成 `request.http`。代理可能使用包含完整 URL 的请求行。保留实际形式，并记录是否经代理。从同次运行的 `report.json` 找到对应文件，再用 `entries[].calls[].request` 核对方法、URL 和请求头。正文使用当次发送的文件，或按报告中 `curl_cmd` 的引号和转义还原。用可用的 `Content-Length` 或客户端记录核对字节数。把 `curl_cmd` 和调试日志作为文本处理。变量已替换的实际请求和可复跑的 `.hurl` 源文件分别归档。
- 单次请求优先使用 `--output` 生成的完整 `response.http`。Hurl 断言失败时，流程可能没有写出 `--output` 文件。此时从同一次运行的对应 `calls[].response` 提取 `http_version`、`status` 和有序响应头，按 `response.body` 的路径读取 `store/` 中的完整正文，将两部分写入 `response.http`。保留失败状态和断言结果。若请求没有收到 HTTP 响应，记录传输错误及已有的请求证据。
- 多条请求、重定向或重试时，按报告中各 `entry` 和 `call` 的顺序逐条配对。为每次交互分别保存请求和响应。`--output` 默认只输出最后一个响应。约定的 SSE 终态从正文核对。保留所有事件、心跳和空行。
- 在发布目录写入文件前，按项目数据要求处理请求、响应和可复跑源文件。用占位符标记敏感值，注明脱敏修改的内容。检查完成后清理本次临时报告和调试日志。

进入用例页复核 URL、请求参数和完整响应。已有 HTTP 文件可用 [render_case.py](../scripts/render_case.py) 生成 Markdown 页。对于凭据请求头，用 `[REDACTED]` 标记字段值。如果正文脱敏改变了字节数，手工编写审阅页并注明原始 `Content-Length` 与归档正文的差异。
