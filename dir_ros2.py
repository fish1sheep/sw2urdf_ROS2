import os
import sys
import shutil
import argparse
import logging
import subprocess
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

try:
    import tkinter as tk
    from tkinter import filedialog
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------
class ROS2PackageSetupError(Exception):
    pass


class DependencyCheckError(ROS2PackageSetupError):
    pass


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def check_file_exists(file_path: str, file_description: str = "文件") -> None:
    if not os.path.isfile(file_path):
        raise DependencyCheckError(f"{file_description} 不存在: {file_path}")


def check_directory_exists(dir_path: str, dir_description: str = "目录") -> None:
    if not os.path.isdir(dir_path):
        raise DependencyCheckError(f"{dir_description} 不存在: {dir_path}")


def check_command_available(command: str) -> bool:
    try:
        subprocess.run(
            [command, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def write_file_content(file_path: str, content: str, encoding: str = "utf-8") -> None:
    parent_dir = os.path.dirname(file_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    with open(file_path, "w", encoding=encoding) as f:
        f.write(content)


def read_file_content(file_path: str, encoding: str = "utf-8") -> str:
    with open(file_path, "r", encoding=encoding) as f:
        return f.read()


def delete_directory(dir_path: str) -> bool:
    if os.path.isdir(dir_path):
        try:
            shutil.rmtree(dir_path)
            logging.info(f"已删除目录: {dir_path}")
            return True
        except Exception as e:
            logging.error(f"删除目录失败: {e}")
            return False
    return False


def delete_file(file_path: str) -> bool:
    if os.path.isfile(file_path):
        try:
            os.remove(file_path)
            logging.info(f"已删除文件: {file_path}")
            return True
        except Exception as e:
            logging.error(f"删除文件失败: {e}")
            return False
    return False


def ensure_directory(dir_path: str) -> None:
    os.makedirs(dir_path, exist_ok=True)


# ---------------------------------------------------------------------------
# 备份管理
# ---------------------------------------------------------------------------
class BackupManager:
    def __init__(self, target_dir: str, enabled: bool = True):
        self.target_dir = target_dir
        self.enabled = enabled
        self.backup_dir = os.path.join(
            target_dir, ".dir_ros2_backup", 
            datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        self._backed_up: list[str] = []

    def backup(self, rel_path: str) -> None:
        if not self.enabled:
            return
        src = os.path.join(self.target_dir, rel_path)
        if not os.path.exists(src):
            return
        dst = os.path.join(self.backup_dir, rel_path)
        ensure_directory(os.path.dirname(dst))
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        self._backed_up.append(rel_path)
        logging.info(f"已备份: {rel_path}")

    def summary(self) -> None:
        if self.enabled and self._backed_up:
            logging.info(f"备份存放位置: {self.backup_dir}")
            logging.info(
                "如需恢复原始文件，可手动从备份目录复制回来。"
            )


# ---------------------------------------------------------------------------
# URDF / SDF 处理（XML 解析，替代硬编码行号）
# ---------------------------------------------------------------------------
def modify_urdf_for_ros2(
    urdf_file: str, xyz: str = "0 0 0.001", rpy: str = "0 0 0"
) -> None:
    """
    使用 xml.etree.ElementTree 在 <robot> 的第一个子元素之前插入
    base_footprint link 和 base_footprint_joint。
    """
    try:
        tree = ET.parse(urdf_file)
    except ET.ParseError as e:
        raise ROS2PackageSetupError(f"URDF 文件解析失败: {e}")

    root = tree.getroot()
    if root.tag != "robot":
        raise ROS2PackageSetupError(
            f"URDF 根标签不是 <robot>，而是 <{root.tag}>"
        )

    # 构造 base_footprint link
    link_elem = ET.Element("link")
    link_elem.set("name", "base_footprint")

    # 构造 base_footprint_joint
    joint_elem = ET.Element("joint")
    joint_elem.set("name", "base_footprint_joint")
    joint_elem.set("type", "fixed")

    origin = ET.SubElement(joint_elem, "origin")
    origin.set("xyz", xyz)
    origin.set("rpy", rpy)

    parent = ET.SubElement(joint_elem, "parent")
    parent.set("link", "base_footprint")

    child = ET.SubElement(joint_elem, "child")
    child.set("link", "base_link")

    # 插入到 root 的最前面
    root.insert(0, link_elem)
    root.insert(1, joint_elem)

    # 尽量保留原始 XML 声明
    original_first_line = ""
    with open(urdf_file, "r", encoding="utf-8") as f:
        first_line = f.readline()
        if first_line.strip().startswith("<?xml"):
            original_first_line = first_line

    # ET 输出（注意：ET 14+ 支持 indent，这里做兼容性处理）
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ")

    tree.write(urdf_file, encoding="utf-8", xml_declaration=False)

    # 如果原来有 XML 声明，补回去
    if original_first_line:
        with open(urdf_file, "r", encoding="utf-8") as f:
            body = f.read()
        with open(urdf_file, "w", encoding="utf-8") as f:
            f.write(original_first_line + body)

    logging.info(f"已在 URDF 中插入 base_footprint (xyz={xyz}, rpy={rpy})")


def ensure_sdf_xml_declaration(sdf_file: str) -> None:
    """
    若 SDF 文件第一行不是 XML 声明，则在开头添加；否则跳过，避免重复。
    """
    with open(sdf_file, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines(keepends=True)
    if lines and lines[0].strip().startswith("<?xml"):
        logging.debug("SDF 已包含 XML 声明，跳过插入")
        return

    xml_decl = '<?xml version="1.0" ?>\n'
    with open(sdf_file, "w", encoding="utf-8") as f:
        f.write(xml_decl + content)
    logging.info("已在 SDF 开头添加 XML 声明")


def cleanup_ros1_launch_files(launch_dir: str) -> None:
    """
    删除 ROS1 格式的 .launch 文件（无 .py 后缀），避免与 ROS2 的 .launch.py 混淆。
    """
    if not os.path.isdir(launch_dir):
        return
    for entry in os.listdir(launch_dir):
        if entry.endswith(".launch") and not entry.endswith(".launch.py"):
            old_path = os.path.join(launch_dir, entry)
            delete_file(old_path)


# ---------------------------------------------------------------------------
# Gazebo SDF 转换
# ---------------------------------------------------------------------------
def convert_urdf_to_sdf(urdf_file: str, output_dir: str) -> str:
    ensure_directory(output_dir)
    sdf_file = os.path.join(output_dir, "model.sdf")

    try:
        result = subprocess.run(
            ["gz", "sdf", "-p", urdf_file],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        with open(sdf_file, "w", encoding="utf-8") as f:
            f.write(result.stdout)
        logging.info(f"URDF 转换为 SDF 成功: {sdf_file}")
        return sdf_file
    except subprocess.CalledProcessError as e:
        raise ROS2PackageSetupError(f"Gazebo SDF 转换失败: {e.stderr}")
    except subprocess.TimeoutExpired:
        raise ROS2PackageSetupError("Gazebo SDF 转换超时")
    except FileNotFoundError:
        raise ROS2PackageSetupError(
            "Gazebo 命令行工具 (gz) 未找到，请确保已安装 Gazebo 并将 gz 添加到系统 PATH"
        )


# ---------------------------------------------------------------------------
# Gazebo 模型部署
# ---------------------------------------------------------------------------
def deploy_gazebo_model(
    package_name: str,
    source_urdf_dir: str,
    gazebo_models_dir: str,
    author_name: str,
    author_email: str,
) -> None:
    target_dir = os.path.join(gazebo_models_dir, package_name)

    if os.path.exists(target_dir):
        logging.info(f"目标目录已存在，先删除: {target_dir}")
        shutil.rmtree(target_dir)

    ensure_directory(target_dir)
    logging.info(f"创建 Gazebo 模型目录: {target_dir}")

    sdf_source = os.path.join(source_urdf_dir, "model.sdf")
    sdf_target = os.path.join(target_dir, "model.sdf")
    if os.path.exists(sdf_source):
        shutil.copy2(sdf_source, sdf_target)
        logging.info("已复制 SDF 文件")

    meshes_source = os.path.join(os.path.dirname(source_urdf_dir), "meshes")
    meshes_target = os.path.join(target_dir, "meshes")
    if os.path.exists(meshes_source):
        shutil.copytree(meshes_source, meshes_target)
        logging.info("已复制 meshes 目录")

    textures_source = os.path.join(os.path.dirname(source_urdf_dir), "textures")
    textures_target = os.path.join(target_dir, "materials", "textures")
    if os.path.exists(textures_source):
        ensure_directory(textures_target)
        shutil.copytree(textures_source, textures_target, dirs_exist_ok=True)
        logging.info("已复制 textures 目录")

    model_config_path = os.path.join(target_dir, "model.config")
    model_config = f"""<?xml version="1.0"?>
<model>
  <name>{package_name}</name>
  <version>1.0</version>
  <sdf version="1.7">model.sdf</sdf>
  <author>
    <name>{author_name}</name>
    <email>{author_email}</email>
  </author>
  <description>
    sw2urdf ROS2 for gazebo11
  </description>
</model>
"""
    write_file_content(model_config_path, model_config)
    logging.info("已创建 model.config")


# ---------------------------------------------------------------------------
# Launch 文件生成
# ---------------------------------------------------------------------------
def create_display_launch(package_name: str, launch_dir: str) -> None:
    launch_file = os.path.join(launch_dir, "display.launch.py")
    content = f"""import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    package_dir = get_package_share_directory('{package_name}')
    urdf_file = os.path.join(package_dir, 'urdf', '{package_name}.urdf')

    with open(urdf_file, 'r') as file:
        robot_description = file.read()

    return LaunchDescription([
        DeclareLaunchArgument('urdf_file', default_value=urdf_file),
        Node(
            package='joint_state_publisher_gui',
            executable='joint_state_publisher_gui',
            name='joint_state_publisher_gui',
            output='screen'
        ),
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{{'robot_description': robot_description}}]
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen'
        ),
    ])
"""
    write_file_content(launch_file, content)
    logging.info(f"已创建 display.launch.py: {launch_file}")


def create_gazebo_launch(
    package_name: str, launch_dir: str, gazebo_models_dir: str
) -> None:
    launch_file = os.path.join(launch_dir, "gazebo.launch.py")
    content = f"""import os
import launch
import launch_ros
from ament_index_python.packages import get_package_share_directory
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    robot_name_in_model = "{package_name}"
    urdf_tutorial_path = get_package_share_directory('{package_name}')
    default_model_path = os.path.join(
        urdf_tutorial_path, 'urdf', '{package_name}.urdf')

    with open(default_model_path, 'r') as urdf_file:
        robot_description = urdf_file.read()

    # 确保 Gazebo 能找到部署的模型目录
    gazebo_models_dir = "{gazebo_models_dir}"
    current_model_path = os.environ.get('GAZEBO_MODEL_PATH', '')
    if gazebo_models_dir:
        if current_model_path:
            os.environ['GAZEBO_MODEL_PATH'] = gazebo_models_dir + ':' + current_model_path
        else:
            os.environ['GAZEBO_MODEL_PATH'] = gazebo_models_dir

    robot_state_publisher_node = launch_ros.actions.Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{{'robot_description': robot_description}}]
    )

    launch_gazebo = launch.actions.IncludeLaunchDescription(
        PythonLaunchDescriptionSource([get_package_share_directory(
            'gazebo_ros'), '/launch', '/gazebo.launch.py']),
    )

    spawn_entity_node = launch_ros.actions.Node(
        package='gazebo_ros',
        executable='spawn_entity.py',
        arguments=['-topic', '/robot_description',
                   '-entity', robot_name_in_model])

    return launch.LaunchDescription([
        robot_state_publisher_node,
        launch_gazebo,
        spawn_entity_node
    ])
"""
    write_file_content(launch_file, content)
    logging.info(f"已创建 gazebo.launch.py: {launch_file}")


# ---------------------------------------------------------------------------
# CMakeLists.txt / package.xml 生成
# ---------------------------------------------------------------------------
def create_cmakelists(package_name: str, target_dir: str) -> None:
    cmake_file = os.path.join(target_dir, "CMakeLists.txt")
    content = f"""cmake_minimum_required(VERSION 3.8)
project({package_name})

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(robot_state_publisher REQUIRED)
find_package(rviz2 REQUIRED)
find_package(gazebo_ros REQUIRED)

install(DIRECTORY launch config meshes urdf
    DESTINATION share/${{PROJECT_NAME}})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
"""
    write_file_content(cmake_file, content)
    logging.info(f"已创建 CMakeLists.txt: {cmake_file}")


def create_package_xml(package_name: str, target_dir: str) -> None:
    xml_file = os.path.join(target_dir, "package.xml")
    content = f"""<?xml version="1.0"?>
<?xml-model href="http://download.ros.org/schema/package_format3.xsd" schematypens="http://www.w3.org/2001/XMLSchema"?>
<package format="3">
  <name>{package_name}</name>
  <version>0.0.0</version>
  <description>TODO: Package description</description>
  <maintainer email="robotsheep@todo.todo">robotsheep</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_cmake</buildtool_depend>

  <depend>rclcpp</depend>
  <depend>robot_state_publisher</depend>
  <depend>rviz2</depend>
  <depend>gazebo_ros</depend>

  <test_depend>ament_lint_auto</test_depend>
  <test_depend>ament_lint_common</test_depend>

  <export>
    <build_type>ament_cmake</build_type>
  </export>
</package>
"""
    write_file_content(xml_file, content)
    logging.info(f"已创建 package.xml: {xml_file}")


# ---------------------------------------------------------------------------
# 前置校验
# ---------------------------------------------------------------------------
def validate_prerequisites() -> None:
    if not check_command_available("gz"):
        raise DependencyCheckError(
            "Gazebo 命令行工具 (gz) 不可用。"
            "请确保已安装 Gazebo 并将 gz 添加到系统 PATH。"
        )

    script_dir = os.path.dirname(os.path.abspath(__file__))
    insert_urdf = os.path.join(script_dir, "insert_urdf.txt")
    insert_sdf = os.path.join(script_dir, "insert_sdf.txt")

    # 为向后兼容，仍然检查这两个文件是否存在
    if not os.path.isfile(insert_urdf):
        logging.warning(
            f"insert_urdf.txt 不存在: {insert_urdf}\n"
            "脚本将使用内置默认配置生成 base_footprint。"
        )
    if not os.path.isfile(insert_sdf):
        logging.warning(
            f"insert_sdf.txt 不存在: {insert_sdf}\n"
            "SDF 的 XML 声明将由脚本自动处理。"
        )


# ---------------------------------------------------------------------------
# 目录选择 / 校验
# ---------------------------------------------------------------------------
def select_target_directory() -> str:
    if not TKINTER_AVAILABLE:
        raise ROS2PackageSetupError(
            "tkinter 不可用，请通过命令行参数指定目标目录\n"
            "使用: python dir_ros2.py /path/to/robot_package"
        )

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    directory = filedialog.askdirectory(title="选择目标 ROS2 包目录")

    root.destroy()

    if not directory:
        raise ROS2PackageSetupError("未选择有效目录")

    return directory


def validate_target_directory(target_dir: str, urdf_filename: Optional[str] = None) -> str:
    if not os.path.isdir(target_dir):
        raise ROS2PackageSetupError(f"目标目录不存在: {target_dir}")

    package_name = os.path.basename(target_dir)
    if urdf_filename:
        urdf_file = os.path.join(target_dir, "urdf", urdf_filename)
    else:
        urdf_file = os.path.join(target_dir, "urdf", f"{package_name}.urdf")

    if not os.path.isfile(urdf_file):
        raise ROS2PackageSetupError(
            f"URDF 文件不存在: {urdf_file}\n"
            "目标目录应包含 urdf/<package_name>.urdf 文件，"
            "或通过 --urdf-file 指定文件名。"
        )

    return package_name


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def setup_ros2_package(
    target_directory: str,
    base_footprint_xyz: str = "0 0 0.001",
    base_footprint_rpy: str = "0 0 0",
    author_name: str = "todo",
    author_email: str = "todo@todo.todo",
    gazebo_models_dir: str = "",
    urdf_filename: Optional[str] = None,
    no_backup: bool = False,
) -> None:
    package_name = os.path.basename(target_directory)
    logging.info("=" * 50)
    logging.info(f"开始配置 ROS2 包: {package_name}")
    logging.info(f"目标目录: {target_directory}")
    logging.info("=" * 50)

    # 确定 URDF 文件路径
    if urdf_filename:
        urdf_file = os.path.join(target_directory, "urdf", urdf_filename)
    else:
        urdf_file = os.path.join(target_directory, "urdf", f"{package_name}.urdf")

    # 备份
    backup_mgr = BackupManager(target_directory, enabled=not no_backup)
    backup_mgr.backup("launch")
    backup_mgr.backup("CMakeLists.txt")
    backup_mgr.backup("package.xml")

    # 清理并重建 launch
    launch_dir = os.path.join(target_directory, "launch")
    delete_directory(launch_dir)
    ensure_directory(launch_dir)

    # 清理 ROS1 遗留文件
    cleanup_ros1_launch_files(launch_dir)

    # 删除旧构建文件
    delete_file(os.path.join(target_directory, "CMakeLists.txt"))
    delete_file(os.path.join(target_directory, "package.xml"))

    # 生成 ROS2 标准文件
    create_cmakelists(package_name, target_directory)
    create_package_xml(package_name, target_directory)
    create_display_launch(package_name, launch_dir)

    # 处理 Gazebo 模型目录默认值
    if not gazebo_models_dir:
        gazebo_models_dir = os.path.expanduser("~/.gazebo/models")
    create_gazebo_launch(package_name, launch_dir, gazebo_models_dir)

    # 确保 config 目录存在（CMakeLists.txt 中 install 了 config）
    config_dir = os.path.join(target_directory, "config")
    if not os.path.isdir(config_dir):
        ensure_directory(config_dir)
        logging.info("已创建空的 config 目录（匹配 CMakeLists.txt install 规则）")

    # 使用 XML 解析修改 URDF，插入 base_footprint
    modify_urdf_for_ros2(urdf_file, xyz=base_footprint_xyz, rpy=base_footprint_rpy)

    # URDF -> SDF
    urdf_dir = os.path.join(target_directory, "urdf")
    sdf_file = convert_urdf_to_sdf(urdf_file, urdf_dir)

    # SDF XML 声明（智能判断，避免重复）
    ensure_sdf_xml_declaration(sdf_file)

    # 部署到 Gazebo 模型目录
    deploy_gazebo_model(
        package_name,
        urdf_dir,
        gazebo_models_dir,
        author_name=author_name,
        author_email=author_email,
    )

    # 删除临时 SDF
    temp_sdf = os.path.join(urdf_dir, "model.sdf")
    delete_file(temp_sdf)

    # 输出备份信息
    backup_mgr.summary()

    logging.info("=" * 50)
    logging.info(f"ROS2 包配置完成: {package_name}")
    logging.info("=" * 50)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="ROS2 机器人模型转换与部署工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python dir_ros2.py                                  # 图形界面选择目录
  python dir_ros2.py /path/to/robot_package           # 命令行指定目录
  python dir_ros2.py /path/to/robot_package --verbose # 显示详细日志
  python dir_ros2.py /path/to/robot_package \\
      --base-footprint-xyz "0 0 0.005" \\
      --author-name "Your Name" \\
      --author-email "you@example.com"
        """,
    )
    parser.add_argument(
        "target_directory",
        nargs="?",
        default="",
        help="ROS2 包的目标目录路径",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="跳过依赖项检查",
    )
    parser.add_argument(
        "--base-footprint-xyz",
        default="0 0 0.001",
        help='base_footprint_joint 的 origin xyz（默认: "0 0 0.001"）',
    )
    parser.add_argument(
        "--base-footprint-rpy",
        default="0 0 0",
        help='base_footprint_joint 的 origin rpy（默认: "0 0 0"）',
    )
    parser.add_argument(
        "--author-name",
        default="todo",
        help='model.config 中的作者名（默认: "todo"）',
    )
    parser.add_argument(
        "--author-email",
        default="todo@todo.todo",
        help='model.config 中的作者邮箱（默认: "todo@todo.todo"）',
    )
    parser.add_argument(
        "--gazebo-models-dir",
        default="",
        help="Gazebo 模型部署目录（默认: ~/.gazebo/models）",
    )
    parser.add_argument(
        "--urdf-file",
        default=None,
        help="自定义 URDF 文件名（默认: <package_name>.urdf）",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="转换前不备份原始 launch、CMakeLists.txt、package.xml",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出 DEBUG 级别日志",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="仅输出 WARNING 及以上级别日志",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    try:
        if not args.skip_validation:
            validate_prerequisites()

        if args.target_directory:
            target_directory = os.path.abspath(args.target_directory)
        else:
            target_directory = select_target_directory()

        validate_target_directory(target_directory, urdf_filename=args.urdf_file)
        setup_ros2_package(
            target_directory,
            base_footprint_xyz=args.base_footprint_xyz,
            base_footprint_rpy=args.base_footprint_rpy,
            author_name=args.author_name,
            author_email=args.author_email,
            gazebo_models_dir=args.gazebo_models_dir,
            urdf_filename=args.urdf_file,
            no_backup=args.no_backup,
        )

    except ROS2PackageSetupError as e:
        logging.error(f"错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("\n操作已取消")
        sys.exit(130)
    except Exception:
        logging.error("发生未预期的错误，详细 traceback 如下:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
