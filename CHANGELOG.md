# dir_ros2.py 重构修改说明

## 概述

本次重构针对 `dir_ros2.py` 脚本在**安全性、健壮性、数据安全、可配置性、工程化**五个维度存在的不足进行了系统性改进。所有修改保持对原有工作流的向后兼容，用户仍可以零配置直接运行脚本。

---

## 修改明细

### 1. 安全性：移除命令注入风险

| 维度 | 修改前 | 修改后 | 原因 |
|------|--------|--------|------|
| `subprocess` 调用 | `command = f'gz sdf -p "{urdf_file}"'` 配合 `shell=True` | `subprocess.run(["gz", "sdf", "-p", urdf_file], shell=False, ...)` | 若 URDF 路径包含引号、分号等特殊字符，旧代码存在命令注入风险。新代码使用列表传参，彻底消除该隐患。 |

---

### 2. 健壮性：XML 解析替代硬编码行号

| 维度 | 修改前 | 修改后 | 原因 |
|------|--------|--------|------|
| URDF `base_footprint` 插入 | `insert_content_at_line(insert_urdf_file, urdf_file, 7)` 硬编码第 7 行 | `modify_urdf_for_ros2()` 使用 `xml.etree.ElementTree` 解析 URDF，在 `<robot>` 的第一个子元素前动态插入 | 不同版本 sw2urdf 导出器的注释行数、标签格式可能不同，硬编码行号极易插错位置导致 URDF 损坏。 |
| URDF XML 声明替换 | `replace_first_line(urdf_file, '<?xml version="1.0" ?>')` 强制替换第一行 | 读取原始 XML 声明并保留，仅修改 DOM 结构后写回 | 旧代码会丢弃 `encoding="utf-8"`，若 URDF 含非 ASCII 字符可能导致解析失败。 |
| SDF XML 声明插入 | `insert_content_at_line(insert_sdf_file, sdf_file, 1)` 无条件在首行插入 | `ensure_sdf_xml_declaration()` 先判断文件第一行是否已有 `<?xml`，有才跳过 | `gz sdf -p` 本身就会输出 XML 声明，旧代码会导致 SDF 出现**两个 XML 声明头**，生成非法 XML。 |
| ROS1 遗留文件 | 未处理 | 新增 `cleanup_ros1_launch_files()`，自动删除无 `.py` 后缀的 `.launch` 文件 | 避免 sw2urdf 生成的 ROS1 launch 文件与新生成的 ROS2 `.launch.py` 共存造成混淆。 |

---

### 3. 数据安全：自动备份机制

| 维度 | 修改前 | 修改后 | 原因 |
|------|--------|--------|------|
| 备份策略 | 无备份，直接 `shutil.rmtree(launch_dir)` 和 `os.remove()` | 新增 `BackupManager` 类，在删除前自动将 `launch/`、`CMakeLists.txt`、`package.xml` 复制到 `<target_dir>/.dir_ros2_backup/<timestamp>/` | 脚本运行中途出错（如 `gz` 命令失败）会导致用户目录处于半破坏状态。备份允许用户手动恢复原始文件。 |
| 备份控制 | 无 | `--no-backup` 参数可跳过备份 | 自动化 CI/CD 场景不需要备份，可通过参数关闭。 |

---

### 4. ROS2 launch 文件修正

| 维度 | 修改前 | 修改后 | 原因 |
|------|--------|--------|------|
| `display.launch.py` 中 `rviz2` | `Node(package='rviz2', ..., parameters=[{'robot_description': robot_description}])` | 移除 `rviz2` 节点的 `parameters` 参数 | `rviz2` 通过订阅 `/robot_description` topic 获取模型，不需要也不接受 `robot_description` 参数。旧代码属于误用。 |
| `gazebo.launch.py` 模型路径 | 未设置环境变量 | 在 `generate_launch_description()` 内通过 `os.environ['GAZEBO_MODEL_PATH']` 追加模型部署目录 | 当使用非默认 `--gazebo-models-dir` 时，Gazebo 可能找不到模型。新代码在 launch 时动态注入路径，确保 mesh 正确加载。 |

---

### 5. 可配置性：命令行参数增强

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--base-footprint-xyz` | `"0 0 0.001"` | 自定义 `base_footprint_joint` 的 `origin xyz` |
| `--base-footprint-rpy` | `"0 0 0"` | 自定义 `base_footprint_joint` 的 `origin rpy` |
| `--author-name` | `"todo"` | 替换 `model.config` 中的作者名占位符 |
| `--author-email` | `"todo@todo.todo"` | 替换 `model.config` 中的邮箱占位符 |
| `--gazebo-models-dir` | `"~/.gazebo/models"` | 覆盖 Gazebo 模型部署目录 |
| `--urdf-file` | `<package_name>.urdf` | 允许 URDF 文件名与包名不一致 |
| `--verbose` | `False` | 输出 DEBUG 级别日志 |
| `--quiet` | `False` | 仅输出 WARNING 及以上日志 |
| `--no-backup` | `False` | 跳过备份 |

**使用示例：**

```bash
# 基本用法（与旧版一致）
python dir_ros2.py /path/to/robot_package

# 自定义 base_footprint 高度与作者信息
python dir_ros2.py /path/to/robot_package \
    --base-footprint-xyz "0 0 0.005" \
    --author-name "Your Name" \
    --author-email "you@example.com"

# 使用自定义 URDF 文件名，输出详细日志
python dir_ros2.py /path/to/robot_package \
    --urdf-file "my_robot.urdf" \
    --verbose
```

---

### 6. 工程化改进

| 维度 | 修改前 | 修改后 | 原因 |
|------|--------|--------|------|
| 日志输出 | 全程 `print()` | 使用 Python `logging` 模块，支持 `--verbose` / `--quiet` | 便于集成到自动化工作流，日志级别可控。 |
| 异常处理 | `except Exception as e: print(f"未知错误: {e}")` | `except Exception: traceback.print_exc()` | 旧代码吞掉了完整的 traceback，出问题后几乎无法调试。新代码保留完整堆栈。 |
| `config` 目录 | 未处理 | `ensure_config_directory()`：若不存在则创建空目录 | `CMakeLists.txt` 中 `install(DIRECTORY launch config meshes urdf ...)` 声明了 `config`。缺失该目录不会导致构建失败，但可能产生 CMake 警告。 |
| `insert_urdf.txt` / `insert_sdf.txt` 依赖 | 强制要求文件存在，否则报错退出 | 降级为 `WARNING` 提示，脚本使用内置默认逻辑继续执行 | 这两个文件的内容（`base_footprint` 片段、XML 声明）已内置于脚本逻辑中，不再强依赖外部文本文件。 |

---

### 7. 已删除的函数

以下函数因被 XML 解析方案取代而移除：

- `insert_content_at_line(source_file, target_file, line_number)` — 硬编码行号插入
- `replace_first_line(file_path, new_first_line)` — 硬编码替换首行

---

## 兼容性说明

- **向后兼容**：不传入任何新增参数时，脚本行为与旧版本基本一致（`base_footprint` 默认高度仍为 `0 0 0.001`）。
- `insert_urdf.txt` 与 `insert_sdf.txt` 仍保留在项目目录中，但脚本不再强制依赖它们。用户仍可手动编辑这两个文件作为参考，或用于其他自定义流程。
- 旧版生成的 ROS1 `.launch` 文件会被自动清理，若您需要保留它们，请在运行脚本前自行备份。
