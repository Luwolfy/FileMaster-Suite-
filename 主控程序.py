import os
import sys
import subprocess
import logging
import tkinter as tk
from tkinter import ttk, messagebox

class ToolLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("工具启动器")
        self.root.geometry("700x500")
        self.root.minsize(600, 400)

        # 获取程序所在目录（兼容打包后的exe）
        if getattr(sys, 'frozen', False):
            self.current_dir = os.path.dirname(sys.executable)
        else:
            self.current_dir = os.path.dirname(os.path.abspath(__file__))

        # 配置日志
        log_file = os.path.join(self.current_dir, 'launcher.log')
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            encoding='utf-8'
        )
        logging.info("========== 工具启动器启动 ==========")

        # 存储工具进程信息 {显示名称: {"path": 脚本路径, "process": 进程对象}}
        self.tools = {}
        self.process_dict = {}

        # 初始化界面
        self.create_widgets()
        self.scan_tools()
        self.update_status()

    def create_widgets(self):
        """创建界面控件"""
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Title.TLabel', font=('微软雅黑', 16, 'bold'), padding=10)
        style.configure('Tool.TLabel', font=('微软雅黑', 12), padding=5)
        style.configure('Status.TLabel', font=('微软雅黑', 10), padding=5, width=10)
        style.configure('Big.TButton', font=('微软雅黑', 11), padding=(10, 5))

        # 顶部标题
        title_frame = ttk.Frame(self.root)
        title_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(title_frame, text="工具启动器", style='Title.TLabel').pack(side=tk.LEFT)

        # 全部启动/停止按钮
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        self.all_start_btn = ttk.Button(btn_frame, text="全部启动", style='Big.TButton', command=self.start_all)
        self.all_start_btn.pack(side=tk.LEFT, padx=5)
        self.all_stop_btn = ttk.Button(btn_frame, text="全部停止", style='Big.TButton', command=self.stop_all)
        self.all_stop_btn.pack(side=tk.LEFT, padx=5)

        # 工具列表容器（Canvas + Scrollbar）
        container = ttk.Frame(self.root)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 底部状态栏
        self.status_bar = ttk.Label(self.root, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=2)

    def scan_tools(self):
        """扫描当前目录下的所有.py文件（排除自身），并创建对应行"""
        py_files = [f for f in os.listdir(self.current_dir) if f.endswith('.py') and f != os.path.basename(__file__)]
        if not py_files:
            logging.warning("未找到任何工具脚本")
            ttk.Label(self.scrollable_frame, text="未找到任何工具脚本", style='Tool.TLabel').grid(row=0, column=0, padx=5, pady=5)
            return

        py_files.sort()
        logging.info(f"扫描到 {len(py_files)} 个工具脚本")
        for idx, filename in enumerate(py_files):
            tool_name = os.path.splitext(filename)[0]
            path = os.path.join(self.current_dir, filename)
            self.tools[tool_name] = {"path": path, "process": None}
            self.add_tool_row(idx, tool_name)

    def add_tool_row(self, row, tool_name):
        """在滚动框架中添加一行工具控件"""
        name_label = ttk.Label(self.scrollable_frame, text=tool_name, style='Tool.TLabel')
        name_label.grid(row=row, column=0, sticky=tk.W, padx=5, pady=5)

        status_label = ttk.Label(self.scrollable_frame, text="已停止", style='Status.TLabel', foreground="red")
        status_label.grid(row=row, column=1, padx=5, pady=5)

        start_btn = ttk.Button(self.scrollable_frame, text="启动", style='Big.TButton',
                               command=lambda name=tool_name: self.start_tool(name))
        start_btn.grid(row=row, column=2, padx=5, pady=5)

        stop_btn = ttk.Button(self.scrollable_frame, text="停止", style='Big.TButton',
                              command=lambda name=tool_name: self.stop_tool(name))
        stop_btn.grid(row=row, column=3, padx=5, pady=5)

        self.tools[tool_name]["name_label"] = name_label
        self.tools[tool_name]["status_label"] = status_label
        self.tools[tool_name]["start_btn"] = start_btn
        self.tools[tool_name]["stop_btn"] = stop_btn

        self.scrollable_frame.grid_columnconfigure(0, weight=1)

    def start_tool(self, tool_name):
        """启动指定工具"""
        tool_info = self.tools[tool_name]
        if tool_info["process"] is not None and tool_info["process"].poll() is None:
            logging.info(f"尝试启动 {tool_name}，但已在运行中")
            messagebox.showinfo("提示", f"{tool_name} 已在运行中")
            return
        try:
            process = subprocess.Popen([sys.executable, tool_info["path"]],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
            tool_info["process"] = process
            self.status_bar.config(text=f"{tool_name} 已启动")
            logging.info(f"启动工具: {tool_name}")
            self.update_single_status(tool_name)
        except Exception as e:
            logging.error(f"启动工具 {tool_name} 失败: {e}")
            messagebox.showerror("启动失败", f"无法启动 {tool_name}\n错误信息：{e}")

    def stop_tool(self, tool_name):
        """停止指定工具"""
        tool_info = self.tools[tool_name]
        process = tool_info["process"]
        if process is None or process.poll() is not None:
            logging.info(f"尝试停止 {tool_name}，但未在运行")
            messagebox.showinfo("提示", f"{tool_name} 未在运行")
            return
        try:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            tool_info["process"] = None
            self.status_bar.config(text=f"{tool_name} 已停止")
            logging.info(f"停止工具: {tool_name}")
            self.update_single_status(tool_name)
        except Exception as e:
            logging.error(f"停止工具 {tool_name} 失败: {e}")
            messagebox.showerror("停止失败", f"无法停止 {tool_name}\n错误信息：{e}")

    def start_all(self):
        """启动所有工具"""
        logging.info("执行全部启动")
        for tool_name in self.tools:
            if self.tools[tool_name]["process"] is None or self.tools[tool_name]["process"].poll() is not None:
                self.start_tool(tool_name)

    def stop_all(self):
        """停止所有工具"""
        logging.info("执行全部停止")
        for tool_name in self.tools:
            if self.tools[tool_name]["process"] is not None and self.tools[tool_name]["process"].poll() is None:
                self.stop_tool(tool_name)

    def update_single_status(self, tool_name):
        """更新单个工具的状态标签"""
        tool_info = self.tools[tool_name]
        status_label = tool_info["status_label"]
        process = tool_info["process"]
        if process is not None and process.poll() is None:
            status_label.config(text="运行中", foreground="green")
        else:
            status_label.config(text="已停止", foreground="red")
            if process is not None and process.poll() is not None:
                tool_info["process"] = None

    def update_status(self):
        """定时更新所有工具状态（每1秒检查一次）"""
        for tool_name in self.tools:
            self.update_single_status(tool_name)
        self.root.after(1000, self.update_status)

if __name__ == "__main__":
    root = tk.Tk()
    app = ToolLauncher(root)
    root.mainloop()