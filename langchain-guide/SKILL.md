---
name: langchain-guide
description: LangChain ChatModel 调用实践指南——结构化输出（with_structured_output 替代正则/围栏解析）、工具调用（bind_tools/tool_choice 的真实行为边界、参数的 Pydantic 校验何时生效）、三层重试与超时（max_retries/timeout 真实默认值、with_retry() 与业务回喂重试的分工）、多模型 fallback、同步/异步调用（asyncio.to_thread 的共享线程池上限 vs 原生 ainvoke()）。每条结论都附源码/实测验证，不是转述文档默认值。不负责 Prompt 设计、非 LangChain 框架、Agent 自动执行循环（`create_agent`）/LangGraph 编排。
disable-model-invocation: true
license: MIT
---

# LangChain ChatModel 调用指南

覆盖 LangChain `ChatModel`（以 `ChatOpenAI` / 兼容 OpenAI 协议的第三方网关为主）
调用时最容易被 AI 写成过时/脆弱写法，或凭直觉猜测而未经验证的五块：结构化输出、
工具调用、重试与超时、多模型 fallback、同步/异步调用方式。

每条关键结论都标注了验证依据（源码行为 / 真实模型实测），不是转述文档默认值——
第三方 OpenAI 兼容网关代理的模型经常在细节上偏离 OpenAI 官方行为，文档写的
默认语义不能直接当作这些模型上的事实。

---

## 0. 适用范围与边界

**只管**：
- 结构化输出怎么拿（`with_structured_output()` 而不是手写解析）
- 工具调用怎么绑定、怎么强制调用、参数怎么被 Pydantic 校验、`parallel_tool_calls`
  这类参数实际生效到什么程度
- `max_retries` / `timeout` / `with_retry()` 三层重试分别管什么、别用错层
- `with_fallbacks()` 多模型链组合时的注意事项
- `asyncio.to_thread(llm.invoke)` 和 `await llm.ainvoke()` 的真实区别

**不包含**：
- Prompt 本身怎么写、业务分类口径 → 业务逻辑，本 skill 不管
- 裸调用官方 SDK（`openai.chat.completions.create` 等）→ 参考对应 SDK 文档
- Agent 自动执行循环（`create_agent()` 会自动把 tool_calls 执行完再喂回模型）、
  LangGraph 编排 → 本 skill 只管单次 ChatModel 调用，不管多轮自动循环

---

## 1. 结构化输出：`with_structured_output()`

### 1.1 反模式：手写解析

以下写法是 AI 生成代码里的常见坏味道，一旦看到就该换成 1.2 节的官方 API：

```python
# ❌ 正则从自由文本里抠 JSON——模型多吐一句话就炸
match = re.search(r"\{.*\}", response.content, re.DOTALL)
data = json.loads(match.group())

# ❌ 手动剥围栏——模型换个围栏格式（```json / ``` / 无围栏）就失效
content = response.content.strip()
if content.startswith("```"):
    content = content.split("```")[1].removeprefix("json")

# ❌ 拿到 dict 后手动 .get() 拼 Pydantic 模型——校验形同虚设
result = ClassificationResult(category=raw.get("category", "unknown"))
```

**例外**：如果已经用 `method="json_mode"` 或 `response_format={"type": "json_object"}`
约束过模型，`response.content` 本身就是严格 JSON，直接 `json.loads()` 合理——
反模式特指"从自由文本里正则/剥围栏硬抠"，不是"解析已知合法的 JSON 字符串"。

### 1.2 现代 API

```python
structured_llm = llm.with_structured_output(
    Schema,                       # Pydantic 类，才能拿到校验过的实例
    method="function_calling",    # function_calling | json_schema | json_mode
    include_raw=False,            # True 时拿 {"raw", "parsed", "parsing_error"}
)
result = structured_llm.invoke(messages)   # schema 是 Pydantic 类 → result 直接是该类实例
```

字段说明写 `Field(description=...)`，会进 Schema 直接被模型消费（参考
python-quality skill 的 Pydantic 专项）。

### 1.3 三种 `method` 怎么选——**别假设，去实测**

| method | 原理 | 是否需要在 prompt 里手写 schema 说明 |
|---|---|---|
| `json_schema` | 走供应商的 Structured Outputs API，模型侧强制匹配 schema | 不需要，LangChain 自动生成 |
| `function_calling` | 把 schema 包成一个"工具"强制调用（内部就是第 2 节的 `bind_tools` + 强制 `tool_choice`） | 不需要 |
| `json_mode` | 只保证输出是合法 JSON，**不保证字段匹配 schema** | **需要**，必须自己在 prompt 里写清楚字段结构 |

`json_schema` / `function_calling` 原本是 OpenAI/Anthropic 的能力，很容易想当然
认为"第三方 OpenAI 兼容网关/国产模型/自部署模型"不支持、必须退到 `json_mode`。
**这个假设不可靠——实测过才算数**，很多模型已经跟进支持了 OpenAI 的
Structured Outputs 协议。以下是一次真实测试（同一个 Pydantic schema，三种
method 分别打给两个走第三方 OpenAI 兼容网关代理的国产模型）：

```
== 模型 A（DeepSeek 系）==
  [json_schema     ] OK  parsed=Answer(category='...', score=0.9)   parsing_error=None
  [function_calling] OK  parsed=Answer(category='A', score=0.8)    parsing_error=None
  [json_mode       ] FAIL parsing_error=... 模型把字段名翻译成中文，Pydantic 校验报 Field required

== 模型 B（Kimi 系）==
  [json_schema     ] OK  parsed=Answer(category='...', score=0.99)  parsing_error=None
  [function_calling] OK  parsed=Answer(category='A', score=0.85)   parsing_error=None
  [json_mode       ] FAIL parsing_error=... 同上，字段名被模型自由发挥
```

结论：这两个模型其实**都支持 `json_schema`**，反而是想当然选的 `json_mode`
因为没在 prompt 里写死字段名，被模型"创造性"地翻译/改写了字段名导致校验失败。
"第三方/国产模型只能退到 json_mode"是一个常见的想当然，实测经常会被打破。

**LangChain 自己的保护也别全信**：`with_structured_output` 源码里有一段针对
`method="json_schema"` 的保护——如果 `self.model_name` 以 `gpt-3`/`gpt-4-`
开头或等于 `gpt-4`（这些不支持 OpenAI Structured Outputs），会自动降级成
`function_calling` 并打 warning。**这个保护只认识别 OpenAI 自己的模型名前缀**，
对着第三方网关下的模型名（如 `DeepSeek-V4-Flash`）完全不生效——不会报错也不会
警告，请求原样发给网关，网关/模型能不能处理是它自己的事。换句话说：LangChain
不会替你兜底判断"这个第三方模型到底支不支持 json_schema"，这件事必须自己实测。

**探测方法**（接入新模型/新网关时跑一次，不要在生产代码里每次请求都探测——
这是部署期/接入期的一次性验证，不是运行期逻辑）：

```python
def probe_methods(llm, schema, sample_input):
    """对给定模型逐个尝试三种 method，返回真正跑通的那个（按优先级）。"""
    for method in ("json_schema", "function_calling", "json_mode"):
        try:
            out = llm.with_structured_output(schema, method=method, include_raw=True).invoke(sample_input)
            if out["parsing_error"] is None:
                return method
        except Exception:
            continue
    return None   # 三种都不行，才轮到手写 prompt 约束 + 自定义校验的兜底方案
```

跑完之后把验证结论**写成代码注释固定下来**（参考已有代码里"实测 DeepSeek
无副作用、Kimi 消围栏"这类注释的写法），不要每次调用都重新探测——支持哪种
method 是 (供应商, 模型) 的固有属性，不是每次请求都会变的东西。

### 1.4 `include_raw` + 自定义重试

`with_structured_output()` **不会自动重试**解析失败（第 3 节的 `max_retries`
是另一个层面的重试，见 3.1）。需要"解析失败把错误回喂模型重来一次"就用
`include_raw=True` 拿 `parsing_error` 自己接循环：

```python
structured_llm = llm.with_structured_output(Schema, method="json_schema", include_raw=True)

for attempt in range(2):
    out = structured_llm.invoke(messages)
    if out["parsing_error"] is None:
        result = out["parsed"]
        break
    messages += [out["raw"], HumanMessage(content=f"上次输出无法解析：{out['parsing_error']}，请重新输出。")]
else:
    result = None   # 转人工/默认值等，按调用方语义处理
```

这个手写循环不是反模式——官方 API 本身没有内置这层重试，自己接是合理设计。

---

## 2. 工具调用：`bind_tools()` / `tool_choice`

结构化输出的 `method="function_calling"` 本质上就是这一层的封装（把 schema
包成一个工具、`tool_choice` 强制指向它）。当需要模型调用多个不同工具、或需要
自己控制"要不要执行工具"的流程时，直接用 `bind_tools()`。

### 2.1 定义工具：`@tool` + `args_schema`

```python
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class FlightQuery(BaseModel):
    flight_no: str = Field(description="航班号，如 CA1234")

@tool("get_flight_status", args_schema=FlightQuery)
def get_flight_status(flight_no: str) -> str:
    """查询指定航班号的实时状态。"""
    ...
```

不传 `args_schema` 时 LangChain 会从函数签名自动推断（`infer_schema=True`），
简单场景够用；字段需要额外说明（如格式要求）时显式传 `args_schema` 更可控。

### 2.2 `bind_tools()` 不会自动执行工具

```python
bound = llm.bind_tools([get_flight_status, get_weather])
msg = bound.invoke("CA1234现在什么状态")
msg.tool_calls   # [{"name": "get_flight_status", "args": {"flight_no": "CA1234"}, ...}]
```

`bind_tools()` 只是让模型"知道有哪些工具、决定要不要调用、调用时填什么参数"，
返回的 `AIMessage.tool_calls` 需要**自己执行工具、把结果包成 `ToolMessage`
追加回对话**再调一次模型——这层手动编排不算反模式，`bind_tools()` 本身就没有
自动循环这层功能。如果需要"自动执行工具直到给出最终答案"的完整循环，那是
`create_agent()` 的职责，不在本 skill 范围内。

### 2.3 `tool_choice`：强制调用哪个工具

| 取值 | 效果 |
|---|---|
| `"auto"` / 不传 | 模型自己决定要不要调用、调用哪个（默认） |
| `"<具体工具名>"` | 强制且只能调用这一个工具（结构化输出场景最常用——本质是"提取信息"而非"自由对话"） |
| `"any"` / `"required"` / `True` | 必须调用某个工具，但不限定具体哪个；模型不能只回纯文本 |
| `"none"` | 禁止调用任何工具 |

以下是真实实测（同样两个第三方网关模型，绑定 `get_weather` + `get_flight_status`
两个工具）：

```
[tool_choice="get_flight_status"]  故意问"今天天气怎么样"，仍被强制只调用 get_flight_status —— 生效
[tool_choice="any"]                故意说"你好"，仍被强制调用了某个工具、content 为空 —— 生效
```

**结论：`tool_choice` 强制调用（指定工具名 / "any"）在这两个第三方模型上是可靠的**，
可以放心用它替代"让模型自己判断要不要输出结构化内容"这种更不确定的写法。

### 2.4 `parallel_tool_calls=False`——实测：第三方模型不一定遵守

官方文档说 `parallel_tool_calls=False` 会禁止模型一次返回多个 `tool_calls`。
**实测结果：在上面两个第三方网关模型上，传了 `parallel_tool_calls=False`，
模型依然在一句话里同时返回了 `get_weather` 和 `get_flight_status` 两个
tool_call**——这个参数被静默忽略了，没有报错也没有警告。

这意味着：**如果业务逻辑假定"传了 `parallel_tool_calls=False` 就一定只有
一个 tool_call"，在这类模型上是不安全的假设**。凡是业务上要求"只能有一个
tool_call"（比如强制单工具提取场景，直接用 2.3 节的 `tool_choice="<工具名>"`
更可靠），或者即使传了这个参数也要在代码里防御性校验：

```python
msg = bound.invoke(user_input)
if len(msg.tool_calls) != 1:
    raise ValueError(f"期望恰好 1 个 tool_call，实际 {len(msg.tool_calls)} 个")
```

不要因为传了 `parallel_tool_calls=False` 就认为"下游只需要处理单个 tool_call"，
省略这层校验。

### 2.5 `strict=True`：限制是文档说的，不是 LangChain 客户端会挡的

OpenAI 官方文档对 Structured Outputs 的 strict 模式有限制：字段不能带
`default`，所有字段都要出现在 `required` 里。容易顺着文档得出"用了
`Field(gt=..., default=...)` 会在客户端 schema 转换阶段直接报错"的结论——
**这个结论是错的，实测证伪**：

```python
>>> from langchain_core.utils.function_calling import convert_to_openai_tool
>>> from pydantic import BaseModel, Field
>>> class Bad(BaseModel):
...     score: float = Field(gt=0, le=1, default=0.5, description="置信度")
>>> convert_to_openai_tool(Bad, strict=True)["function"]["parameters"]
{'properties': {'score': {'default': 0.5, 'exclusiveMinimum': 0, 'maximum': 1, ...}},
 'required': ['score'], 'additionalProperties': False, ...}
```

`default`/`exclusiveMinimum`/`maximum` 原样进了 schema，LangChain **不做任何
客户端校验或报错**——它只负责转换，不负责按 OpenAI 的 strict 子集规则挑错。
真打到第三方网关模型（DeepSeek-V4-Flash / Kimi-K2.6-TripCloud）实测，两边都
**正常返回、没报错**，说明这条"限制"在这些后端上根本没被强制执行。

结论：这条限制是不是真的会挡你，**完全取决于后端实现**，不能照抄文档或教程
的说法当成客户端会报错的事实。真 OpenAI 官方 API 上是否会拒绝没有在本环境
验证过——涉及严格模式的字段约束/默认值组合，同样按 1.3 节的方式针对目标
后端实测一次，不要凭教程文章下结论。

### 2.6 工具参数的 Pydantic 校验：只在走 `tool.invoke()` 这条路径时才生效

`args_schema` 定义的 Pydantic 校验**不是白拿的**——它只在你调用
`tool.invoke(tool_call)` 这条 LangChain 官方路径时才会触发；如果绕开它、自己拿
`msg.tool_calls[i]["args"]` 这个原始 dict 直接去调用底层 Python 函数，校验和类型
转换全部被跳过。实测（`args_schema` 里 `passenger_count: int`，模型吐出的是
字符串 `"5"`）：

```python
# ✅ 走 tool.invoke()：Pydantic 做类型转换，底层函数收到的是 int(5)
get_flight_status.invoke(tool_call)
#   底层函数实际收到: <class 'int'> 5

# ❌ 跳过 invoke，直接摸 args dict 调用底层函数：拿到什么类型模型给什么类型
get_flight_status.func(**tool_call["args"])
#   底层函数实际收到: <class 'str'> '5'   —— 没报错，但类型没被转换
```

传非法值（比如 `passenger_count: "abc"`）时区别更明显：走 `tool.invoke()` 会抛
`pydantic.ValidationError`，明确说清楚哪个字段、什么错误；跳过 `invoke()` 直接
调用底层函数则是拿着错误类型硬跑，failure mode 取决于函数内部逻辑（可能直接
抛无关的 `TypeError`，也可能悄悄跑出错误结果）。

**手写 Agent 循环时**（自己遍历 `msg.tool_calls` 执行工具，不用 `create_agent()`
的场景），一定要用 `tool.invoke(call)` 而不是 `tool.func(**call["args"])`——
前者是"模型输出 → 校验过的类型 → 业务函数"，后者是"模型输出 → 业务函数"，
少了中间这层保护，等于让模型的自由输出直接摸到业务代码：

```python
# ✅ 正确：走 invoke，校验/类型转换 + 自动产出 ToolMessage
tools_by_name = {t.name: t for t in tools}
for call in msg.tool_calls:
    tool_msg = tools_by_name[call["name"]].invoke(call)   # ToolMessage，含 tool_call_id
    messages.append(tool_msg)

# ❌ 错误：跳过校验，自己拼 ToolMessage
for call in msg.tool_calls:
    result = tools_by_name[call["name"]].func(**call["args"])
    messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
```

两种写法产出的 `ToolMessage` 看起来一样，区别只在中间那一步有没有让模型的
原始参数先过一遍 Pydantic——这正是本节开头提的问题的答案：**工具参数需要
Pydantic 校验，但这层校验是 LangChain 提供的可选机制，不是自动内置在
"模型返回 tool_calls"这一步里的，用错调用方式等于没校验。**

---

## 3. 三层重试与超时：`max_retries` / `timeout` / `with_retry()`

### 3.1 真实默认值（源码实测，`langchain-openai` 1.4.1 + `openai` 2.53.0）

```python
>>> ChatOpenAI.model_fields["max_retries"].default
None
>>> ChatOpenAI.model_fields["request_timeout"].default   # 即 timeout 参数
None
```

`ChatOpenAI` 上这两个字段默认都是 `None`，**不是"不重试"/"不超时"**——`None`
的含义是"不传给底层 openai SDK 客户端"，交给 SDK 自己的默认值：

```python
>>> from openai._constants import DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES
>>> DEFAULT_TIMEOUT
Timeout(connect=5.0, read=600, write=600, pool=600)
>>> DEFAULT_MAX_RETRIES
2
```

即：**不传 `max_retries` 就是重试 2 次**（对连接失败/超时/429/5xx 这类可重试
错误，httpx 层面自动重试，重试期间当前线程/协程会被占住）；**不传 `timeout`
就是读超时 600 秒**。这两条在 `BaseChatOpenAI.validate_environment` 源码里能
直接验证——`max_retries` 是 `None` 时压根不会被塞进传给 SDK 的
`client_params`，走的是 SDK 自身默认值，不是 LangChain 又定义了一份默认值。

### 3.2 为什么通常要显式覆盖 `timeout`

600 秒的读超时对大多数在线业务调用场景（用户等着看结果、或有线程池限制）都
过长——一次挂起的调用会占死一个线程/连接 600 秒。常见做法是按业务能接受的
等待上限**显式硬编码**一个更短的值（不建议做成可配置项——超时预算是代码逻辑
的一部分，不是运维会频繁调的旋钮；参考 karpathy-guidelines 里"要不改代码就能
调"的三问）：

```python
llm = ChatOpenAI(
    model=model_name,
    timeout=60,       # 显式覆盖 SDK 默认的 600s 读超时——挂起调用不占死线程太久
    # max_retries 留空，吃 SDK 默认的 2 次网络层重试即可，通常不需要覆盖
)
```

### 3.3 `max_retries` 是网络层重试，不是业务层重试

这两次自动重试只覆盖**连接失败/HTTP 层错误**（超时、429、5xx），**不覆盖**
"HTTP 200 但内容解析失败"这类业务层问题——业务层的重试（如 JSON 解析失败回喂
模型重来）要用 1.4 节的手写循环单独接，两者不是一回事，别把 `max_retries`
当成"模型输出格式不对也会重试"。

### 3.4 `Runnable.with_retry()`：另一层重试，别指望它纠正系统性错误

LangChain 在 `max_retries`（openai SDK 网络层）之外还有一层**Runnable 级**
重试，`.with_retry()`，任何 `Runnable`（包括 `llm`、`with_structured_output()`
之后的链）都能调：

```python
retrying = structured_llm.with_retry(
    stop_after_attempt=3,                    # 默认 3 次
    retry_if_exception_type=(Exception,),    # 默认捕获所有异常，包括解析失败抛出的 OutputParserException
)
```

看起来像是能顶替 1.4 节的手写回喂循环，**实测证明不行**：反查源码，
`RunnableRetry._invoke` 每次重试都是 `super().invoke(input_, ...)`——**拿一模一样
的输入再调一次**，不会把上次的错误信息追加进对话。真打到真实网关模型验证：
故意用 `method="json_mode"` 且不给 schema 说明（1.3 节已知会失败的场景），
包一层 `with_retry(stop_after_attempt=3)`：

```
实测：底层模型被调用 3 次，3 次全部失败——每次都用同一个 input 重新问一遍，
模型每次都用同样的方式把字段名翻译成中文，重试到用尽次数后照样抛异常。
```

结论：`.with_retry()` 对**偶发性**问题（网络抖动、模型偶尔抽风一次输出格式）
有用；但当失败原因是**系统性**的（prompt 没写清楚、schema 说明缺失，导致模型
每次都用同一种方式错），`.with_retry()` 只是拿同样的输入重复撞墙，白白多耗
2 次调用还是失败。这种场景要用 1.4 节"把错误回喂给模型"的写法，让模型看到
自己上次错在哪，而不是简单重试。

三层重试怎么分工，不是选一个：`max_retries` 管连接失败/5xx 这类瞬时网络问题
（几乎总该开着，用 SDK 默认值即可）；`.with_retry()` 适合"模型本身输出不稳定、
换一次采样可能就对了"的场景（比如 temperature > 0 时偶发解析失败）；1.4 节的
回喂循环适合"错误是可诊断的，模型看到错误信息能自我纠正"的场景。三层不是
互斥关系，但别用错误的那层去解决另一层的问题。

---

## 4. 多模型 fallback：`with_fallbacks()`

```python
primary = ChatOpenAI(model="model-a", timeout=60)
fallback = ChatOpenAI(model="model-b", timeout=60)
chain = primary.with_fallbacks([fallback])
```

注意两点：
- primary 异常（含超时、`max_retries` 耗尽后的最终异常）才会触发 fallback；
  primary 返回 200 但内容不对（比如结构化输出解析失败）**不会**自动触发
  fallback，除非你在 `with_structured_output(...).with_fallbacks(...)` 这一层
  显式让解析失败也抛异常（`include_raw=False` 时解析失败会 raise，可以被
  `with_fallbacks` 捕获；`include_raw=True` 时不会 raise，`with_fallbacks`
  就看不到这个"失败"）。
- primary 和 fallback 如果是不同供应商/不同模型，1.3 节 method 的支持度、
  2.4 节 `parallel_tool_calls` 是否真的生效，**都要两边分别实测**，不能假设
  primary 验证通过 fallback 也没问题。

---

## 5. 同步调用 vs 异步调用：`asyncio.to_thread(llm.invoke)` 不等于 `await llm.ainvoke()`

在异步代码里调 LLM，常见写法是把同步的 `.invoke()` 包一层
`asyncio.to_thread()`——这样写能跑通，但不是最优解，`ChatOpenAI` 本身就有
原生异步方法，没必要绕这一层。

### 5.1 `asyncio.to_thread` 吃的是进程共享的默认线程池

`asyncio.to_thread()` 底层是 `loop.run_in_executor(None, ...)`——`None` 意味着
用进程级的**默认** `ThreadPoolExecutor`，大小是 `min(32, os.cpu_count() + 4)`
（这台机器上算出来是 18），而且**这个池是整个进程共享的**：不只是你的 LLM
调用在用它，代码里任何别的 `asyncio.to_thread`/`loop.run_in_executor(None, ...)`
调用都在抢同一批线程。并发数一旦超过池大小，多出来的调用要排队等线程释放，
即使网络本身撑得住更高并发。

实测对比（同样并发 25 个"耗时 1 秒"的任务，一组走 `asyncio.to_thread` 包同步
阻塞调用，一组走原生 `asyncio.sleep` 模拟真异步 I/O）：

```
25 个并发「模拟同步调用」(asyncio.to_thread + time.sleep(1)) 耗时: 2.01s   —— 池只有 18 个线程，25 个任务分两批跑
25 个并发「真异步调用」(asyncio.sleep(1))                    耗时: 1.01s   —— 不占线程，全部真并发
```

这不是 LLM/LangChain 特有的行为，是 Python `asyncio.to_thread` 本身的机制——但
放到"并发处理一批消息、每条都要调 LLM"这种场景（比如消费者从队列批量拉消息
后并发处理）就是实打实的吞吐瓶颈：并发数一旦超过默认线程池大小，多出来的调用
只是在排队，不是在真正并发请求网关。

### 5.2 原生异步：`await llm.ainvoke()`

反查 `BaseChatOpenAI._agenerate` 源码，走的是真正的异步 HTTP 客户端：

```python
raw_response = await self.root_async_client.chat.completions.with_raw_response.parse(**payload)
```

`root_async_client` 是 `openai.AsyncOpenAI`，用的是 httpx 的异步传输，不占用
线程池里的任何一个线程，并发数不受 5.1 节那个默认上限约束。`with_structured_output()`
/ `bind_tools()` / `with_fallbacks()` 产出的链同样支持 `.ainvoke()`——实测
`primary.with_fallbacks([fallback]).ainvoke(...)` 对着真实网关模型正常跑通，
换成异步调用不用放弃 fallback。

**什么时候值得换**：如果代码本来就跑在异步框架里（FastAPI、异步消费者循环等），
现在的写法是"把 `.invoke()` 包一层 `asyncio.to_thread` 只是为了能在 `async def`
里调用"，直接换成 `await llm.ainvoke(...)`（或链的 `.ainvoke()`）大概率是纯收益——
少一层线程池依赖，高并发下不会因为线程池打满而排队。并发量很小（比如单个请求
处理一次）时两者观感一样，这层差异只有在并发调用数接近或超过默认线程池大小时
才会显现。

---

## 6. 版本自查

`with_structured_output` / `bind_tools` 的默认值和支持的 method 在不同
provider 包之间不完全一致，且同一个包里子类可能覆盖基类默认值。**不要直接
假设文档/记忆里的默认值就是本地装的版本的行为**，用 `inspect` 反查一次：

```python
import inspect
from langchain_openai import ChatOpenAI
print(inspect.signature(ChatOpenAI.with_structured_output))
print(inspect.signature(ChatOpenAI.bind_tools))
print(ChatOpenAI.model_fields["max_retries"].default)
```

例如 `langchain_openai` 里，基类 `BaseChatOpenAI.with_structured_output` 默认
`method="function_calling"`，但 `ChatOpenAI` 子类覆盖成了 `"json_schema"`——
只看基类文档会得出错误结论；`max_retries`/`timeout` 同理，字段默认值是
`None`，真正生效的默认值在底层 `openai` SDK 包里，两个包的版本都要对上。

---

**这个 skill 在起作用的标志：**
- 结构化输出走 `with_structured_output()` + Pydantic，看不到正则/剥围栏抠 JSON
- 手写 Agent 循环执行工具走 `tool.invoke(call)`，不会绕开校验直接
  `tool.func(**call["args"])`
- `method` / `tool_choice` / `parallel_tool_calls` 这类"看文档就下结论"的参数
  都有实测依据，不是照抄"第三方模型只能用 json_mode""传了
  `parallel_tool_calls=False` 就一定只有一个 tool_call"这类未经验证的经验之谈
- `timeout` 显式覆盖过默认的 600s；`max_retries` 没被误认为能覆盖业务层解析
  失败；系统性失败没有被指望靠 `.with_retry()` 盲重试解决
- 异步代码里调 LLM 用的是 `await llm.ainvoke()`，不是图省事把 `.invoke()` 包一层
  `asyncio.to_thread()` 占用共享线程池
