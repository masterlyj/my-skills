---
name: python-quality
version: 1.0.0
description: Python 代码可读性规范：模块 docstring、Google 风格函数/类 docstring、行内注释。当编写或审查 Python 代码，需要确保文档和注释清晰、符合主流开源项目标准时使用。与 karpathy-guidelines 分工：karpathy 管“写什么”，本规范管“怎么写”。不负责 Git 提交消息（见 git-commit），不负责代码格式（交给 black/isort/ruff），不负责类型注解正确性（交给 mypy/pyright）。
license: MIT
---

# Python 代码质量规范

本规范聚焦**可读性**：文档与注释的写法。  
提交消息由 `git-commit` skill 单独维护，设计取舍由 `karpathy-guidelines` 负责。  
当出现重叠时，以功能更聚焦的 skill 为准。

---

## 0. 适用范围与边界

本 skill 只规定以下内容的写法：
- 所有 `.py` 文件的 module docstring
- 公开函数 / 类 / 方法的 docstring（含 Pydantic 模型）
- 行内注释（WHY 类、晦涩逻辑的 WHAT 类）

**不包含**：
- Git 提交消息 → 见 `git-commit` skill
- 代码风格（空格、命名、import 排序）→ 交给 black / isort / ruff
- 类型注解本身 → 交给 mypy / pyright，本规范不重复类型信息
- 函数该不该写、写多少 → 见 `karpathy-guidelines`，本规范只解决“写出来能不能读懂”

---

## 1. Module Docstring（文件级）

每个 `.py` 文件都必须有 module docstring，作为模块的**第一条语句**（位于 `from __future__ import` 之前）。

**格式：**
```python
"""一句话描述本模块的职责。（以句号结尾）

可选：模块的整体描述——它做什么、解决什么问题；简单模块只留一句摘要即可。

对外暴露（公开 API 较多时列出）：
  ClassName      — 一句话说明
  function_name  — 一句话说明
"""
```

**规则：**
- 第一行是**单句摘要**，不超过 72 字符，以句号结尾
- 摘要与后续段落之间空一行
- 不要写"这个文件包含..."或"本模块定义了..."，直接说职责
- 私有模块（`_xxx.py`）也要写，帮助维护者理解意图
- **例外**：测试文件（`test_*.py` / `*_test.py`）不需要 module docstring，除非有额外信息（运行方式、特殊依赖、外部依赖等）

**反例：**
```python
# ❌ 完全没有 module docstring
from __future__ import annotations
import os
```

```python
# ❌ 摘要太模糊，没说清职责
"""工具函数。"""
```

```python
# ✅ 一句话说明职责
"""评测阶段的检索执行层，直接调用本地 RagPipeline，避免 HTTP 绕路。"""
```

---

## 2. Google 风格 Docstring（函数 / 类 / 方法）

本项目统一使用 **Google 风格**（`Args:`/`Returns:`/`Raises:` 字段化，与 Sphinx、NumPy 并列为三大主流 docstring 风格）。

### 2.1 函数 / 方法

```python
def function(arg1: int, arg2: str, arg3: bool = False) -> list[str]:
    """一句话摘要，描述函数做什么。（祈使句，如"返回..."、"构建..."、"过滤..."）

    可选的补充说明段落，解释算法、约束或边界条件。

    Args:
        arg1: 参数描述，不重复类型注解中已有的信息。
        arg2: 描述含义和预期格式。
        arg3: 可选参数说明默认行为。

    Returns:
        返回值描述。如果返回 tuple，列出各元素含义。
        例：(pipeline, min_score) 元组，pipeline 可调用 retrieve()。

    Raises:
        ValueError: 何种情况下抛出，一句话描述触发条件。
        RuntimeError: 另一种异常情况。
    """
```

生成器示例：

```python
def iter_chunks(text: str, size: int) -> Iterator[str]:
    """把文本按固定长度切块，逐块返回。

    Args:
        text: 待切分的文本。
        size: 每块的最大长度。

    Yields:
        下一块文本，长度不超过 size。
    """
    for i in range(0, len(text), size):
        yield text[i:i + size]
```

**规则：**
- 摘要用**祈使句**（"返回" 不是 "会返回"）——遵循 PEP 257，本项目统一选用；**`@property` 例外**：用描述式（`"""The Bigtable path."""`）
- 摘要不超过 72 字符，以句号结尾
- 只有一个参数且含义显而易见时，可以省略 Args 段
- `*args`/`**kwargs` 在 Args 段直接列 `*args:`/`**kwargs:`，一句话说明，不逐个展开
- 生成器函数（`yield`/`yield from`）用 `Yields:` 段代替 `Returns:`，描述**单次 yield 的值**；异步生成器同理
- 返回 `None` 时省略 Returns 段；摘要已说明返回值/产出值时也可省略
- Raises 只列调用方应当预见并处理的异常，不列 API 违规或内部实现产生的异常；不抛异常时省略
- 带 `@override` 的重写方法可简写 `"""See base class."""`，除非行为实质改变了基类契约
- 私有函数（`_xxx`）写简短摘要即可，不强制完整 Args/Returns

### 2.2 类

```python
class MyClass:
    """一句话描述该类实例代表什么。

    可选的详细说明。

    Args:
        param1: __init__ 参数说明（写在类 docstring，不写在 __init__）。
        param2: 另一个参数。

    Attributes:
        attribute1: 公开属性说明（不含 property，property 有自己的 docstring）。
    """
```

**规则：**
- 摘要描述**实例代表什么**，不要写"这是一个类..."或"用于..."
- `__init__` 参数的 `Args:` 段写在类 docstring，不写在 `__init__` 方法里（Google 允许两种，本项目统一选用类 docstring）
- `Attributes:` 只列公开属性（不含 `property`，不含私有属性）
- `Exception` 子类：描述异常**代表什么**（如「缺少必需的配置项。」），不描述何时被抛出

### 2.3 Pydantic 模型专项（FastAPI / BaseModel）

Pydantic 模型的字段描述有专用机制，规则与普通类不同。

**注意：** 类 docstring 会自动成为 JSON Schema 的 `description` 字段——LLM/agent 框架会消费它来决定工具选择，改 docstring 就是改运行时行为。

**核心规则：**
- 类 docstring 只写**摘要**（一句话），不写 `Attributes:` 块
- 字段描述统一用 `Field(description=...)`，直接进入 JSON Schema / Swagger UI
- `Field(description=...)` 使用中文，与代码注释和 docstring 语言保持一致
- 不要同时写 `Attributes:` 块和 `Field(description=...)`——重复维护，易不一致

```python
# ✅ 类摘要 + Field 描述
class CreatePipelineRequest(BaseModel):
    """创建 pipeline 的请求体，包含数据源与处理配置。"""

    name: str = Field(description="pipeline 的唯一名称，用于后续引用。")
    source_type: SourceType = Field(description="数据源类型，决定下载器的选择。")
    chunk_size: int = Field(default=512, gt=0, description="分块大小，单位为 token 数。")
```

**可选替代：attribute docstring（Pydantic ≥ 2.7）**

启用 `use_attribute_docstrings=True` 后，字段下方的 docstring 自动成为字段描述，代码更紧凑：

```python
class CreatePipelineRequest(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    name: str
    """pipeline 的唯一名称，用于后续引用。"""

    source_type: SourceType
    """数据源类型，决定下载器的选择。"""
```

两种方式选一种统一使用，不要混用。同时给了 `Field(description=...)` 时，Field 优先。权衡：attribute docstring 更 Pythonic，但有 AST 解析开销（仅类定义时一次性）且需要源码可用。

**例外：** 模型作为 LLM structured output 的 schema（如 instructor）时，类 docstring 可写**提取指令**，这不是属性描述，不算冗余：

```python
class UserDetails(BaseModel):
    """从文本中提取用户信息，保持字段命名一致。"""

    name: str = Field(description="用户的姓名。")
    age: int = Field(description="用户的年龄。")
```

### 2.4 摘要句动词参考

| 用途 | 推荐动词 |
|------|--------|
| 查询/读取 | 返回、读取、获取、查询 |
| 创建/构建 | 构建、创建、初始化、生成 |
| 删除/清理 | 删除、移除、清除 |
| 更新/设置 | 更新、修改、设置 |
| 转换 | 将...转换为、解析、映射 |
| 过滤/验证 | 过滤、校验、检查 |
| 加载/存储 | 加载、保存、写入 |
| 执行/控制 | 执行、调用、发送、启动、停止 |

仅为常见场景速查，非封闭集合。

---

## 3. 行内注释规范

### 3.1 何时加注释

**加注释的情况：**

WHY 类（首选）：
- 隐藏约束：`# ES 8.x 的 knn 语法与 7.x 不兼容，此处不能用 query_vector_builder`
- 绕过 bug：`# httpx 在 Windows 上不支持 Unix socket，强制用 TCP`
- 非显然的算法选择：`# 减去最大值再 exp，防止数值上溢`
- 兼容性说明：`# 兼容 jina（relevance_score）和 bge（score）两种响应字段名`

WHAT 类（仅限晦涩逻辑）：
- 多步骤复杂逻辑块：条件组合、状态跳转、多层嵌套不易一眼看懂时，在块首用一行说明该段意图，帮助 reviewer 定向阅读，而非逐行推导

**段首意图注释（paragraph comment）：**

函数体包含多个逻辑段时，在每段开头用一行注释说明该段**做什么**（意图），不说怎么做。帮助 reviewer 快速定位和跳读。

- 判断标准：删掉代码只留注释，能看出函数的执行步骤，说明注释到位
- 不要给显而易见的单行 / 单步逻辑加段首注释
- 当段首注释超过 5 条，优先将各段提取为独立函数——段首注释本身就是天然的函数名来源

```python
# ✅ 复杂块首注释（说明意图，不是逐行复述）
# 先下载附件再预处理 HTML，确保内嵌图片路径已落盘可供改写
att_dir = email_dir / "attachments"
if email.attachments:
    att_dir.mkdir(exist_ok=True)
    for att in email.attachments:
        ...
preprocessed = _preprocess_html(body_html, att_dir)
```

**注释纪律：** 注释写**完整的契约与安全使用事实**——过期的注释比没有注释更危险。不写推理过程（"先试了 X 不行，所以改用 Y"是 review 历史，不进代码库）；直接、具体，避免比喻。

**不加注释的情况：**
```python
# ❌ 说废话（代码本身就是说明）
i += 1  # i 加 1
return []  # 返回空列表

# ❌ 复述变量名
user_list = []  # 用户列表

# ❌ 对简单逻辑加块首注释（代码已足够清晰）
# 检查是否为空
if not items:
    return
```

### 3.2 格式要求

```python
# 块注释：# 后一个空格，与代码同缩进
# 多段落之间用仅含 # 的空行分隔：
#
# 第二段补充边界条件或历史背景。
result = heavy_computation()

x = x + 1  # 行尾注释：代码后两个空格，# 后一个空格
```

**换行规则：** 注释按**语义换行**（一句一行），不要在句中按字符数硬折。改一句话只影响一行 diff，中文不会从中间截断。超长单句先精简措辞，实在需要折行时在标点或连词后断开。

```python
# ❌ 按字符数硬折，句子从中间断开
# 这个函数负责从数据库中读取用户的历
# 史订单记录并按时间排序返回给调用方

# ✅ 一句一行，语义完整
# 从数据库读取用户的历史订单记录，按时间排序返回。
```

### 3.3 TODO / FIXME

```python
# TODO(作者或 issue): 描述待办事项——必须包含具体日期或触发事件
# TODO: PROJ-1234 - 当所有客户端支持 v2 后移除此兼容层
# FIXME: 描述已知 bug 及原因
```

---

**这些规范在起作用的标志：** 新人看 module docstring 就知道这个文件做什么；行内注释回答的是"为什么这样写"而不是"写了什么"；注释里看不到推理过程和 review 历史。
