# dir_ros2.py 使用说明

`dir_ros2.py` 是一个将 SolidWorks sw2urdf 导出目录一键转换为 ROS2 功能包的工具脚本。它会自动生成 `CMakeLists.txt`、`package.xml`、`display.launch.py`、`gazebo.launch.py`，插入 `base_footprint`，完成 URDF→SDF 转换，并将模型部署到 Gazebo 模型目录。

---

## 安装依赖

```bash
# ROS2 与 Gazebo（必须）
sudo apt install ros-$ROS_DISTRO-robot-state-publisher ros-$ROS_DISTRO-joint-state-publisher ros-$ROS_DISTRO-gazebo-ros-pkgs gazebo

# 图形界面选择目录时需要（可选）
sudo apt install python3-tk
```

---

## 基本用法

### 命令行指定目录

```bash
python3 dir_ros2.py /path/to/your_robot_package
```

### 图形界面选择目录

```bash
python3 dir_ros2.py
```

脚本会弹出文件夹选择框，选中后自动完成转换。

---

## 输入目录要求

脚本要求目标目录至少包含：

```
your_robot_package/
├── urdf/
│   └── your_robot_package.urdf      # 默认文件名需与目录名一致
└── meshes/
    └── *.STL
```

如果 URDF 文件名与目录名不同，使用 `--urdf-file` 指定。

---

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `target_directory` | — | 目标目录路径（位置参数，可省略以使用 GUI） |
| `--base-footprint-xyz` | `"0 0 0.001"` | `base_footprint_joint` 的原点位置 |
| `--base-footprint-rpy` | `"0 0 0"` | `base_footprint_joint` 的原点姿态 |
| `--author-name` | `"todo"` | Gazebo `model.config` 作者名 |
| `--author-email` | `"todo@todo.todo"` | Gazebo `model.config` 作者邮箱 |
| `--gazebo-models-dir` | `"~/.gazebo/models"` | Gazebo 模型部署路径 |
| `--urdf-file` | `<包名>.urdf` | 自定义 URDF 文件名 |
| `--no-backup` | `False` | 禁用自动备份 |
| `--verbose` | `False` | 输出 DEBUG 日志 |
| `--quiet` | `False` | 只输出 WARNING 及以上日志 |
| `--skip-validation` | `False` | 跳过 `gz` 命令可用性检查 |

---

## 使用示例

**最简转换：**
```bash
python3 dir_ros2.py ~/Downloads/my_arm
```

**自定义 base_footprint 高度：**
```bash
python3 dir_ros2.py ~/Downloads/my_arm --base-footprint-xyz "0 0 0.05"
```

**URDF 文件名与目录名不一致：**
```bash
python3 dir_ros2.py ~/Downloads/my_arm --urdf-file "robot.urdf"
```

**完整参数：**
```bash
python3 dir_ros2.py ~/Downloads/my_arm \
    --base-footprint-xyz "0 0 0.005" \
    --base-footprint-rpy "0 0 0" \
    --author-name "Alice" \
    --author-email "alice@example.com" \
    --verbose
```

**CI/CD 静默运行（不备份、不弹窗）：**
```bash
python3 dir_ros2.py ~/Downloads/my_arm --no-backup --quiet
```

---

## 脚本做了什么

1. **备份** — 将 `launch/`、`CMakeLists.txt`、`package.xml` 复制到 `.dir_ros2_backup/<时间戳>/`
2. **清理** — 删除旧 `launch/`、`CMakeLists.txt`、`package.xml` 及 ROS1 遗留 `.launch` 文件
3. **生成** — 创建 ROS2 标准的 `CMakeLists.txt`、`package.xml`
4. **Launch** — 生成 `display.launch.py`（Rviz2）和 `gazebo.launch.py`（Gazebo）
5. **修复 URDF** — 用 XML 解析器在 `<robot>` 下插入 `base_footprint` link 与 joint
6. **转 SDF** — 调用 `gz sdf -p` 将 URDF 转为 SDF
7. **部署模型** — 将 SDF、meshes、textures 复制到 Gazebo 模型目录，并生成 `model.config`
8. **清理临时文件** — 删除 `urdf/model.sdf` 临时文件

---

## 输出结构

转换后的包目录：

```
my_arm/
├── CMakeLists.txt
├── package.xml
├── launch/
│   ├── display.launch.py
│   └── gazebo.launch.py
├── config/                 # 若原目录没有，脚本会自动创建空目录
├── meshes/
│   └── *.STL
└── urdf/
    └── my_arm.urdf         # 已插入 base_footprint
```

Gazebo 模型目录：

```
~/.gazebo/models/my_arm/
├── model.config
├── model.sdf
└── meshes/
    └── *.STL
```

---

## 备份与还原

脚本默认会自动备份。如需恢复原始文件：

```bash
cd my_arm
rm -rf launch CMakeLists.txt package.xml

cp -r .dir_ros2_backup/20260115_143022/launch .
cp .dir_ros2_backup/20260115_143022/CMakeLists.txt .
cp .dir_ros2_backup/20260115_143022/package.xml .
```

---

## 后续步骤

将转换后的目录移入 ROS2 工作空间并编译：

```bash
mv my_arm ~/ros2_ws/src/
cd ~/ros2_ws
colcon build --packages-select my_arm
source install/setup.bash
```

启动可视化：

```bash
# Rviz2
ros2 launch my_arm display.launch.py

# Gazebo
ros2 launch my_arm gazebo.launch.py
```

---

## 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| `gz` 命令未找到 | Gazebo 未安装或未加入 PATH | `sudo apt install gazebo` |
| URDF 文件不存在 | 默认查找 `<包名>.urdf`，实际文件名不同 | 使用 `--urdf-file` 指定 |
| Rviz2 看不到模型 | Fixed Frame 未设为 `base_footprint` | 在 Rviz2 中设置 Fixed Frame 为 `base_footprint` |
| Gazebo 中 mesh 缺失 | Gazebo 未找到模型目录 | 检查 `~/.gazebo/models/<包名>/meshes/` 是否存在 `.STL` |
