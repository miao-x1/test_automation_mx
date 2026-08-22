# 数据库设计文档

## 一、ER图说明

### 实体关系图

```
┌─────────────────┐
│      Task       │ 1
│   (任务表)      │───────┐
├─────────────────┤       │
│ id (PK)         │       │
│ task_name       │       │
│ status          │       │
│ error_message   │       │
│ created_at      │       │
│ updated_at      │       │
└─────────────────┘       │
        │                 │
        │ 1               │ 1
        │                 │
        ├─────────────────┼─────────────────┐
        │                 │                 │
        │ *               │ 1               │ 1
        │                 │                 │
┌───────▼────────┐ ┌──────▼──────────┐ ┌──▼─────────────┐
│  ImageFile     │ │ AnalysisResult  │ │     Script     │
│  (图片表)      │ │  (分析结果表)   │ │   (脚本表)     │
├────────────────┤ ├─────────────────┤ ├────────────────┤
│ id (PK)        │ │ id (PK)         │ │ id (PK)        │
│ task_id (FK)   │ │ task_id (FK,UK) │ │ task_id (FK,UK)│
│ original_name  │ │ agent_type      │ │ script_type    │
│ file_path (UK) │ │ page_type       │ │ script_content │
│ file_size      │ │ elements_json   │ │ script_language│
│ file_type      │ │ interactions_   │ │ file_path      │
│ width          │ │ layout_json     │ │ created_at     │
│ height         │ │ analysis_summary│ │ updated_at     │
│ md5_hash       │ │ raw_output      │ └────────────────┘
│ created_at     │ │ created_at      │
│ updated_at     │ │ updated_at      │
└────────────────┘ └─────────────────┘

PK = Primary Key (主键)
FK = Foreign Key (外键)
UK = Unique Key (唯一键)
```

### 关系说明

1. **Task → ImageFile**: 一对多 (1:N)
   - 一个任务可以有多张图片
   - 级联删除：删除任务时自动删除关联的所有图片

2. **Task → AnalysisResult**: 一对一 (1:1)
   - 一个任务对应一个分析结果
   - 级联删除：删除任务时自动删除关联的分析结果

3. **Task → Script**: 一对一 (1:1)
   - 一个任务对应一个生成的脚本
   - 级联删除：删除任务时自动删除关联的脚本

---

## 二、表结构设计

### 2.1 Task (任务表)

**表名**: `task`

**说明**: 核心业务表，记录每个UI自动化测试任务的基本信息和状态。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | INT | PK, AUTO_INCREMENT | - | 主键ID |
| task_name | VARCHAR(255) | NOT NULL, INDEX | - | 任务名称 |
| status | ENUM | NOT NULL, INDEX | 'pending' | 任务状态 |
| error_message | VARCHAR(1024) | NULL | - | 错误信息 |
| created_at | DATETIME | NOT NULL | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | NOT NULL | CURRENT_TIMESTAMP | 更新时间 |

**索引**:
- PRIMARY KEY: `id`
- INDEX: `idx_task_name` (`task_name`)
- INDEX: `idx_status` (`status`)
- INDEX: `idx_status_created` (`status`, `created_at`) - 复合索引

**枚举值** (`status`):
- `pending`: 待处理
- `processing`: 处理中
- `success`: 成功
- `failed`: 失败

---

### 2.2 ImageFile (图片表)

**表名**: `image_file`

**说明**: 存储上传的UI原型图或页面截图信息，支持一个任务多张图片。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | INT | PK, AUTO_INCREMENT | - | 主键ID |
| task_id | INT | FK, NOT NULL, INDEX | - | 任务ID |
| original_filename | VARCHAR(255) | NOT NULL | - | 原始文件名 |
| file_path | VARCHAR(512) | NOT NULL, UNIQUE | - | 文件存储路径 |
| file_size | BIGINT | NOT NULL | - | 文件大小(字节) |
| file_type | VARCHAR(50) | NOT NULL | - | 文件MIME类型 |
| width | INT | NULL | - | 图片宽度 |
| height | INT | NULL | - | 图片高度 |
| md5_hash | CHAR(32) | NULL, INDEX | - | 文件MD5哈希值 |
| created_at | DATETIME | NOT NULL | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | NOT NULL | CURRENT_TIMESTAMP | 更新时间 |

**索引**:
- PRIMARY KEY: `id`
- UNIQUE KEY: `uk_file_path` (`file_path`)
- INDEX: `idx_task_id` (`task_id`)
- INDEX: `idx_md5_hash` (`md5_hash`)
- INDEX: `idx_task_created` (`task_id`, `created_at`) - 复合索引

**外键**:
- `fk_image_task`: `task_id` → `task.id` (ON DELETE CASCADE)

---

### 2.3 AnalysisResult (分析结果表)

**表名**: `analysis_result`

**说明**: 存储AI Agent对UI图片的分析结果，包括识别的元素、交互和布局信息。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | INT | PK, AUTO_INCREMENT | - | 主键ID |
| task_id | INT | FK, UNIQUE, NOT NULL | - | 任务ID |
| agent_type | VARCHAR(50) | NOT NULL | - | 使用的Agent类型 |
| page_type | VARCHAR(100) | NULL | - | 页面类型 |
| elements_json | TEXT | NULL | - | UI元素JSON |
| interactions_json | TEXT | NULL | - | 交互操作JSON |
| layout_json | TEXT | NULL | - | 布局信息JSON |
| analysis_summary | TEXT | NULL | - | 分析总结 |
| raw_output | TEXT | NULL | - | Agent原始输出 |
| created_at | DATETIME | NOT NULL | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | NOT NULL | CURRENT_TIMESTAMP | 更新时间 |

**索引**:
- PRIMARY KEY: `id`
- UNIQUE KEY: `uk_task_id` (`task_id`)
- INDEX: `idx_task_id` (`task_id`)
- INDEX: `idx_agent_type` (`agent_type`)

**外键**:
- `fk_analysis_task`: `task_id` → `task.id` (ON DELETE CASCADE)

---

### 2.4 Script (脚本表)

**表名**: `script`

**说明**: 存储生成的Playwright测试脚本。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | INT | PK, AUTO_INCREMENT | - | 主键ID |
| task_id | INT | FK, UNIQUE, NOT NULL | - | 任务ID |
| script_type | VARCHAR(50) | NOT NULL | 'playwright' | 脚本类型 |
| script_content | TEXT | NOT NULL | - | 脚本内容 |
| script_language | VARCHAR(20) | NOT NULL | 'python' | 脚本语言 |
| file_path | VARCHAR(512) | NULL | - | 脚本文件路径 |
| created_at | DATETIME | NOT NULL | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | NOT NULL | CURRENT_TIMESTAMP | 更新时间 |

**索引**:
- PRIMARY KEY: `id`
- UNIQUE KEY: `uk_task_id` (`task_id`)
- INDEX: `idx_task_id` (`task_id`)
- INDEX: `idx_script_type` (`script_type`)

**外键**:
- `fk_script_task`: `task_id` → `task.id` (ON DELETE CASCADE)

---

## 三、索引设计说明

### 3.1 主键索引
所有表都有自增主键 `id`，自动创建聚簇索引。

### 3.2 外键索引
所有外键字段自动创建索引，优化JOIN查询性能。

### 3.3 单列索引
- `task.task_name`: 支持按任务名称搜索
- `task.status`: 支持按状态筛选任务
- `image_file.md5_hash`: 支持文件去重检测

### 3.4 唯一索引
- `image_file.file_path`: 防止文件路径重复
- `analysis_result.task_id`: 保证一对一关系
- `script.task_id`: 保证一对一关系

### 3.5 复合索引
- `task(status, created_at)`: 优化"按状态+时间排序"的查询
- `image_file(task_id, created_at)`: 优化"获取任务的图片列表"查询

---

## 四、外键约束说明

### 4.1 级联删除策略

所有外键都设置了 `ON DELETE CASCADE`，确保数据一致性：

- 删除Task时，自动删除关联的：
  - 所有ImageFile记录
  - AnalysisResult记录（如果存在）
  - Script记录（如果存在）

### 4.2 外键列表

| 外键名称 | 子表 | 子表字段 | 父表 | 父表字段 | 删除策略 |
|---------|------|---------|------|---------|---------|
| fk_image_task | image_file | task_id | task | id | CASCADE |
| fk_analysis_task | analysis_result | task_id | task | id | CASCADE |
| fk_script_task | script | task_id | task | id | CASCADE |

---

## 五、BaseModel设计

### 5.1 基类说明

所有模型继承自 `BaseModel`，自动提供：

```python
class BaseModel(Base):
    __abstract__ = True
    
    id: 主键ID (自增)
    created_at: 创建时间 (自动)
    updated_at: 更新时间 (自动)
    
    to_dict(): 转换为字典
    __repr__(): 字符串表示
```

### 5.2 优势

1. **代码复用**: 公共字段统一管理
2. **时间戳**: 自动记录创建/更新时间
3. **类型安全**: SQLAlchemy 2.x 类型提示
4. **工具方法**: 内置序列化和调试方法

---

## 六、业务流程与数据流

```
用户上传图片
    ↓
创建Task记录 (status=pending)
    ↓
保存ImageFile记录(s)
    ↓
启动分析 (status=processing)
    ↓
Agent分析图片
    ↓
创建AnalysisResult记录
    ↓
生成测试脚本
    ↓
创建Script记录
    ↓
更新Task (status=success)
    ↓
前端展示完整结果
```

---

## 七、使用Alembic迁移

### 7.1 初始化迁移

```bash
cd backend
alembic upgrade head
```

### 7.2 创建新迁移

```bash
alembic revision --autogenerate -m "描述"
```

### 7.3 回滚

```bash
alembic downgrade -1
```

---

## 八、数据库配置

### 8.1 开发环境 (SQLite)

```bash
USE_SQLITE=True
SQLITE_PATH=data/test_automation.db
```

### 8.2 生产环境 (MySQL)

```bash
USE_SQLITE=False
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=test_automation
```

---

## 九、性能优化建议

1. **分页查询**: 使用 LIMIT/OFFSET
2. **覆盖索引**: 复合索引包含查询字段
3. **避免N+1**: 使用 `lazy="selectin"` 预加载关联
4. **分区表**: 后期可按时间分区 `task` 表
5. **读写分离**: 生产环境配置主从复制

---

## 十、扩展预留

### 10.1 可能的新表

- `task_execution`: 任务执行记录
- `test_report`: 测试报告
- `user`: 用户表（多租户）
- `project`: 项目表（组织管理）

### 10.2 字段扩展

- `task.priority`: 任务优先级
- `task.tags`: 标签（JSON）
- `analysis_result.confidence`: 置信度
- `script.version`: 脚本版本

---

**设计原则**: 
✅ 满足第一范式（1NF）  
✅ 满足第二范式（2NF）  
✅ 满足第三范式（3NF）  
✅ 外键完整性约束  
✅ 索引优化查询性能  
✅ 级联删除保证数据一致性

---

## 索引设计

| 类型 | 索引 | 说明 |
|------|------|------|
| 主键 | 所有表 `id` | 自动聚簇索引 |
| 单列 | `task.task_name` | 按名称搜索 |
| 单列 | `task.status` | 按状态筛选 |
| 单列 | `image_file.md5_hash` | 文件去重 |
| 唯一 | `image_file.file_path` | 防止路径重复 |
| 唯一 | `analysis_result.task_id` | 保证一对一 |
| 唯一 | `script.task_id` | 保证一对一 |
| 复合 | `task(status, created_at)` | 优化状态+时间查询 |
| 复合 | `image_file(task_id, created_at)` | 优化任务图片列表 |

---

## ORM 模型架构

### BaseModel (通用基类)

```python
class BaseModel(Base):
    __abstract__ = True
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, onupdate=datetime.now)

    def to_dict(self)
    def __repr__(self)
```

### 关系预加载

```python
images = relationship("ImageFile", lazy="selectin")
analysis_result = relationship("AnalysisResult", lazy="selectin")
script = relationship("Script", lazy="selectin")
```

避免 N+1 查询，提升性能。

### 级联删除

```python
ForeignKey("task.id", ondelete="CASCADE")
cascade="all, delete-orphan"
```

删除 Task 时自动清理所有关联数据。

---

## 业务流程

```
1. 用户上传图片
2. 创建 Task 记录 (status=pending)，保存 ImageFile
3. 启动分析 (status=processing)
4. Agent 分析图片
5. 保存 AnalysisResult (elements_json, interactions_json, layout_json)
6. 生成 Playwright 脚本
7. 保存 Script (script_content, script_type, script_language)
8. 更新 Task (status=success)
9. 前端展示完整结果
```

---

## 使用指南

### 开发环境

```bash
cd backend
uvicorn app.main:app --reload
# 自动创建表，无需手动迁移
```

### 生产环境 (MySQL)

```bash
# Alembic 迁移（推荐）
cd backend
alembic upgrade head

# 或 SQL 直接导入
mysql -u root -p < docs/database_schema.sql
```

### 代码统计

| 类型 | 数量 | 说明 |
|------|------|------|
| 数据表 | 4 | task, image_file, analysis_result, script |
| ORM模型 | 5 | BaseModel + 4个业务模型 |
| 索引 | 11 | 主键4 + 单列3 + 唯一3 + 复合2 |
| 外键 | 3 | 全部级联删除 |
| 关联关系 | 3 | 1:N + 1:1 + 1:1 |
