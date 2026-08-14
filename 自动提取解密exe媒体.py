import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import os
import subprocess
import shutil
import tempfile

class RPAExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RPA 批量提取工具 v2")
        self.root.geometry("800x700")
        self.root.resizable(True, True)

        self.folder_list = []
        self.output_dir = tk.StringVar()
        self.keep_structure = tk.BooleanVar(value=True)
        self.is_running = False
        self.rpa_count = 0
        self.processed_count = 0

        self.create_widgets()
        self.check_environment()

    def create_widgets(self):
        # ---------- 输入文件夹区域 ----------
        input_frame = ttk.LabelFrame(self.root, text="1. 选择游戏文件夹（可添加多个）", padding=5)
        input_frame.pack(fill=tk.X, padx=10, pady=5)

        # 按钮行
        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=0, column=0, columnspan=4, sticky="w", pady=5)

        btn_add_single = ttk.Button(btn_frame, text="添加单个文件夹", command=self.add_folder)
        btn_add_single.pack(side=tk.LEFT, padx=2)

        btn_add_batch = ttk.Button(btn_frame, text="批量添加（搜索子目录）", command=self.batch_add_folders)
        btn_add_batch.pack(side=tk.LEFT, padx=2)

        btn_remove = ttk.Button(btn_frame, text="移除选中", command=self.remove_selected)
        btn_remove.pack(side=tk.LEFT, padx=2)

        btn_clear = ttk.Button(btn_frame, text="清空列表", command=self.clear_list)
        btn_clear.pack(side=tk.LEFT, padx=2)

        # 列表
        self.listbox = tk.Listbox(input_frame, selectmode=tk.EXTENDED, height=6)
        self.listbox.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
        scrollbar = ttk.Scrollbar(input_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.grid(row=1, column=3, sticky="ns")
        self.listbox.config(yscrollcommand=scrollbar.set)

        # 统计信息
        self.count_label = ttk.Label(input_frame, text="已添加 0 个文件夹")
        self.count_label.grid(row=2, column=0, columnspan=4, sticky="w", padx=5, pady=2)

        input_frame.columnconfigure(0, weight=1)

        # ---------- 输出目录区域 ----------
        output_frame = ttk.LabelFrame(self.root, text="2. 导出文件夹", padding=5)
        output_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(output_frame, text="输出目录:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        entry_out = ttk.Entry(output_frame, textvariable=self.output_dir, width=50)
        entry_out.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        btn_browse = ttk.Button(output_frame, text="浏览...", command=self.select_output)
        btn_browse.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        output_frame.columnconfigure(1, weight=1)

        # ---------- 选项区域 ----------
        option_frame = ttk.LabelFrame(self.root, text="3. 提取选项", padding=5)
        option_frame.pack(fill=tk.X, padx=10, pady=5)

        chk_keep = ttk.Checkbutton(option_frame, text="保留原文件夹框架（不勾选则所有文件扁平化到根目录）",
                                   variable=self.keep_structure)
        chk_keep.pack(anchor="w", padx=5, pady=5)

        # ---------- 进度条 ----------
        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill=tk.X, padx=10, pady=5)

        self.progress = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, length=400, mode='determinate')
        self.progress.pack(fill=tk.X, expand=True)

        self.status_label = ttk.Label(progress_frame, text="就绪")
        self.status_label.pack(anchor="w", pady=2)

        # ---------- 日志区域 ----------
        log_frame = ttk.LabelFrame(self.root, text="日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, state='normal', font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ---------- 底部按钮 ----------
        btn_frame_bottom = ttk.Frame(self.root)
        btn_frame_bottom.pack(fill=tk.X, padx=10, pady=10)

        btn_start = ttk.Button(btn_frame_bottom, text="开始提取", command=self.start_extraction)
        btn_start.pack(side=tk.RIGHT, padx=5)

        btn_guide = ttk.Button(btn_frame_bottom, text="新手引导", command=self.show_guide)
        btn_guide.pack(side=tk.RIGHT, padx=5)

    def check_environment(self):
        """检查 unrpa 命令行是否可用"""
        try:
            result = subprocess.run(["unrpa", "--help"], capture_output=True, timeout=2)
            if result.returncode == 0:
                self.log("✅ 环境检查通过：unrpa 命令行可用。")
            else:
                self.log("⚠️ 警告：unrpa 命令行返回异常，请检查安装。")
        except FileNotFoundError:
            self.log("❌ 错误：未找到 unrpa 命令，请先安装。")
            messagebox.showwarning("环境缺失", "未找到 unrpa 命令。\n请打开 CMD 执行：pip install unrpa")

    def log(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def update_folder_count(self):
        self.count_label.config(text=f"已添加 {len(self.folder_list)} 个文件夹")

    def add_folder(self):
        """单个添加文件夹"""
        folder = filedialog.askdirectory(title="选择游戏文件夹（包含 RPA 的目录）")
        if folder:
            if folder not in self.folder_list:
                self.folder_list.append(folder)
                self.listbox.insert(tk.END, folder)
                self.log(f"✅ 已添加: {folder}")
                self.update_folder_count()
            else:
                messagebox.showinfo("提示", "该文件夹已添加。")

    def batch_add_folders(self):
        """批量添加：选择父目录，自动添加所有包含 RPA 的子目录"""
        parent_dir = filedialog.askdirectory(title="选择父目录（将自动搜索所有子文件夹中的 RPA）")
        if not parent_dir:
            return

        self.log(f"🔍 正在搜索: {parent_dir}")
        added_count = 0
        # 遍历一级子目录
        for item in os.listdir(parent_dir):
            sub_path = os.path.join(parent_dir, item)
            if os.path.isdir(sub_path):
                # 检查该子目录下是否有 .rpa 文件
                has_rpa = False
                for root, dirs, files in os.walk(sub_path):
                    for f in files:
                        if f.lower().endswith('.rpa'):
                            has_rpa = True
                            break
                    if has_rpa:
                        break
                if has_rpa:
                    if sub_path not in self.folder_list:
                        self.folder_list.append(sub_path)
                        self.listbox.insert(tk.END, sub_path)
                        self.log(f"✅ 批量添加: {sub_path}")
                        added_count += 1

        self.update_folder_count()
        self.log(f"📦 批量添加完成，共新增 {added_count} 个文件夹。")
        if added_count == 0:
            messagebox.showinfo("提示", f"在 {parent_dir} 下未找到任何包含 RPA 文件的子文件夹。")

    def remove_selected(self):
        selected = self.listbox.curselection()
        if not selected:
            messagebox.showinfo("提示", "请先在列表中选中要移除的项。")
            return
        for idx in reversed(selected):
            path = self.listbox.get(idx)
            self.folder_list.remove(path)
            self.listbox.delete(idx)
            self.log(f"🗑️ 已移除: {path}")
        self.update_folder_count()

    def clear_list(self):
        if self.folder_list:
            if messagebox.askyesno("确认", "确定要清空所有已添加的文件夹吗？"):
                self.folder_list.clear()
                self.listbox.delete(0, tk.END)
                self.update_folder_count()
                self.log("🗑️ 已清空所有文件夹列表。")

    def select_output(self):
        folder = filedialog.askdirectory(title="选择导出目录")
        if folder:
            self.output_dir.set(folder)

    def start_extraction(self):
        if self.is_running:
            messagebox.showinfo("提示", "正在运行，请等待完成。")
            return

        if not self.folder_list:
            messagebox.showerror("错误", "请至少添加一个游戏文件夹。")
            return

        out_dir = self.output_dir.get().strip()
        if not out_dir:
            messagebox.showerror("错误", "请指定导出目录。")
            return

        os.makedirs(out_dir, exist_ok=True)

        # 扫描所有 RPA
        rpa_files = []
        for folder in self.folder_list:
            for root, dirs, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith('.rpa'):
                        rpa_files.append(os.path.join(root, f))

        if not rpa_files:
            messagebox.showinfo("提示", "未找到任何 .rpa 文件。")
            return

        self.log(f"📂 共发现 {len(rpa_files)} 个 RPA 文件。")
        self.rpa_count = len(rpa_files)
        self.processed_count = 0
        self.progress['maximum'] = self.rpa_count
        self.progress['value'] = 0
        self.status_label.config(text="准备提取...")
        self.is_running = True

        thread = threading.Thread(target=self.extract_worker, args=(rpa_files, out_dir), daemon=True)
        thread.start()

    def extract_worker(self, rpa_files, out_dir):
        keep = self.keep_structure.get()

        for rpa in rpa_files:
            if not os.path.isfile(rpa):
                self.log(f"⚠️ 跳过不存在的文件: {rpa}")
                self.processed_count += 1
                self.root.after(0, self.update_progress, self.processed_count)
                continue

            # 确定目标子目录
            rpa_dir = os.path.dirname(rpa)
            parent_dir = os.path.dirname(rpa_dir)
            game_name = os.path.basename(parent_dir)
            if not game_name:
                game_name = os.path.basename(rpa_dir)
            if not game_name:
                game_name = "unknown"

            if keep:
                target_root = os.path.join(out_dir, game_name)
            else:
                target_root = out_dir

            os.makedirs(target_root, exist_ok=True)

            self.log(f"▶️ 开始提取: {os.path.basename(rpa)} -> {target_root}")

            try:
                if keep:
                    # 保留结构
                    cmd = ["unrpa", "-mp", target_root, rpa]
                    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                    if result.returncode != 0:
                        self.log(f"⚠️ 返回码 {result.returncode}: {result.stderr.strip()}")
                    else:
                        self.log(f"✅ 完成提取: {os.path.basename(rpa)}")
                else:
                    # 扁平化
                    with tempfile.TemporaryDirectory() as tmpdir:
                        cmd = ["unrpa", "-mp", tmpdir, rpa]
                        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                        if result.returncode != 0:
                            self.log(f"⚠️ 返回码 {result.returncode}: {result.stderr.strip()}")
                        else:
                            # 移动文件
                            for root, dirs, files in os.walk(tmpdir):
                                for f in files:
                                    src = os.path.join(root, f)
                                    dst = os.path.join(target_root, f)
                                    base, ext = os.path.splitext(f)
                                    counter = 1
                                    while os.path.exists(dst):
                                        new_name = f"{base}_{counter}{ext}"
                                        dst = os.path.join(target_root, new_name)
                                        counter += 1
                                    shutil.move(src, dst)
                            self.log(f"✅ 完成提取（扁平化）: {os.path.basename(rpa)}")
            except Exception as e:
                self.log(f"❌ 提取 {os.path.basename(rpa)} 时出错: {e}")

            self.processed_count += 1
            self.root.after(0, self.update_progress, self.processed_count)

        self.root.after(0, self.finish_extraction)

    def update_progress(self, value):
        self.progress['value'] = value
        self.status_label.config(text=f"已处理 {value}/{self.rpa_count} 个 RPA 文件")
        self.root.update_idletasks()

    def finish_extraction(self):
        self.is_running = False
        self.status_label.config(text="🎉 提取完成！")
        messagebox.showinfo("完成", "所有 RPA 文件已提取完毕！")
        self.log("🎉 全部提取完成。")

    def show_guide(self):
        guide = tk.Toplevel(self.root)
        guide.title("新手引导 - 环境搭建")
        guide.geometry("620x450")
        guide.resizable(True, True)
        text = scrolledtext.ScrolledText(guide, wrap=tk.WORD, font=("Consolas", 10))
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        content = """
【环境搭建步骤】

1. 安装 Python（如果尚未安装）
   - 访问 https://www.python.org/downloads/
   - 下载最新版 Python（建议 3.8 以上）
   - 安装时务必勾选 “Add Python to PATH”

2. 安装 unrpa 命令行工具
   - 打开 CMD，执行：
     pip install unrpa
   - 等待安装完成。

3. 运行本工具
   - 双击 rpa_extractor_gui_v2.py 或在 CMD 中执行：
     python rpa_extractor_gui_v2.py

4. 使用步骤
   - 点击“添加单个文件夹”逐个选择游戏目录
   - 或点击“批量添加”选择父目录，自动搜索所有包含 RPA 的子文件夹
   - 选择导出目录
   - 勾选“保留文件夹框架”则保持原内部目录结构
   - 点击“开始提取”，等待完成

常见问题：
- 如果提示 “unrpa” 不是内部或外部命令，请确保 Python Scripts 目录在 PATH 中。
- 如果提取中断，请检查磁盘空间和文件权限。
- 加密的 RPA 暂不支持。
"""
        text.insert(tk.END, content)
        text.config(state='disabled')

if __name__ == "__main__":
    root = tk.Tk()
    app = RPAExtractorApp(root)
    root.mainloop()