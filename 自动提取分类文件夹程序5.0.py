# -*- coding: utf-8 -*-
"""
文件分类工具 v2 – 带可调频词预览、滚动条、可自由拖动的界面

功能概览
---------
* 通过「文件名包含关键字」把文件移动或复制到目标子文件夹
* 高频词统计阈值可自行设置（默认出现 ≥2 次即显示）
* 左侧预览区：① 高频词列表（带滚动条） ② 分类树（双击打开文件，水平/垂直滚动条）
* 支持批量重命名、查找重复文件等实用小工具
* 所有耗时操作在子线程完成，UI 始终保持响应
"""

import os
import re
import sys
import shutil
import hashlib
import subprocess
import threading
from collections import defaultdict, Counter
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

# --------------------------------------------------------------
# 主窗口
# --------------------------------------------------------------
class FileCategorizerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("文件分类工具 v2 – 带预览")
        self.geometry("960x750")
        self.minsize(800, 600)

        # ---------- 主题 & 字体 ----------
        style = ttk.Style(self)
        style.theme_use("clam")                       # 更现代的外观
        default_font = ("Microsoft YaHei", 10)
        self.option_add("*Font", default_font)

        # ---------- 变量 ----------
        self.src_dir = tk.StringVar()
        self.dst_dir = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.move_files = tk.BooleanVar(value=True)   # True=移动，False=复制
        self.rules = []                               # [{match:…, folder:…}, …]

        # 高频词阈值（用户可在 UI 中自行修改）
        self.freq_threshold = tk.IntVar(value=2)

        # ---------- 主布局 ----------
        self._create_main_panes()
        self._build_right_ui()
        self.update_status()

    # --------------------------------------------------------------
    #  主布局（左侧预览 + 右侧功能区，使用 PanedWindow 支持拖动缩放）
    # --------------------------------------------------------------
    def _create_main_panes(self):
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # ---- 左侧：文件预览 ----
        self.preview_frame = ttk.Frame(self.paned, width=340)
        self.paned.add(self.preview_frame, weight=1)   # weight=1 代表可拖动

        # 高频词标题 + 阈值 Spinbox
        top_frame = ttk.Frame(self.preview_frame)
        top_frame.pack(fill=tk.X, pady=(5, 0), padx=5)

        ttk.Label(top_frame,
                  text="文件名高频词（出现 ≥ 次）",
                  font=("Microsoft YaHei", 10, "bold")).pack(side=tk.LEFT)

        ttk.Spinbox(top_frame,
                    from_=1, to=100,
                    textvariable=self.freq_threshold,
                    width=4,
                    justify=tk.CENTER).pack(side=tk.RIGHT, padx=5)

        # 高频词 Listbox + 滚动条
        lb_frame = ttk.Frame(self.preview_frame)
        lb_frame.pack(fill=tk.BOTH, expand=False, padx=5, pady=2)

        self.freq_listbox = tk.Listbox(lb_frame,
                                       height=6,
                                       activestyle="dotbox")
        self.freq_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        freq_scroll = ttk.Scrollbar(lb_frame,
                                   orient=tk.VERTICAL,
                                   command=self.freq_listbox.yview)
        freq_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.freq_listbox.config(yscrollcommand=freq_scroll.set)

        # 分类预览 Treeview + 双滚动条
        ttk.Label(self.preview_frame,
                  text="分类预览（双击文件打开）",
                  font=("Microsoft YaHei", 10, "bold")).pack(anchor=tk.W,
                                                         padx=5,
                                                         pady=(8, 0))

        tree_container = ttk.Frame(self.preview_frame)
        tree_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        # Treeview
        self.preview_tree = ttk.Treeview(tree_container,
                                        columns=("fullpath",),
                                        show="tree")
        self.preview_tree.heading("#0", text="目标文件夹 / 文件名", anchor=tk.W)

        self.preview_tree.column("#0", minwidth=150, width=250, anchor=tk.W)
        self.preview_tree.column("fullpath", width=0, stretch=False)   # 隐藏列，仅存储完整路径

        self.preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 记录每个 item 对应的完整路径（仅对文件节点有效）
        self._tree_item_path = {}

        # 垂直滚动条
        v_scroll = ttk.Scrollbar(tree_container,
                                 orient=tk.VERTICAL,
                                 command=self.preview_tree.yview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_tree.configure(yscrollcommand=v_scroll.set)

        # 水平滚动条（文件名过长时能够横向滚动）
        h_scroll = ttk.Scrollbar(self.preview_frame,
                                 orient=tk.HORIZONTAL,
                                 command=self.preview_tree.xview)
        h_scroll.pack(fill=tk.X, padx=5, pady=(0, 5))
        self.preview_tree.configure(xscrollcommand=h_scroll.set)

        # 双击打开文件
        self.preview_tree.bind("<Double-1>", self._on_tree_double_click)

        # ---- 右侧：功能区 ----
        self.right_frame = ttk.Frame(self.paned, padding="5")
        self.paned.add(self.right_frame, weight=3)

    # --------------------------------------------------------------
    #  右侧功能区 UI（保持 4.0 功能，仅布局稍作优化）
    # --------------------------------------------------------------
    def _build_right_ui(self):
        # ---------- 1️⃣ 路径选择 ----------
        path_frame = ttk.LabelFrame(self.right_frame,
                                    text="文件夹选择",
                                    padding="5")
        path_frame.pack(fill=tk.X, pady=5)

        ttk.Label(path_frame, text="源文件夹:").grid(row=0,
                                                    column=0,
                                                    sticky=tk.W)
        ttk.Entry(path_frame,
                  textvariable=self.src_dir,
                  width=50).grid(row=0, column=1, padx=5)
        ttk.Button(path_frame,
                   text="浏览…",
                   command=self.select_src).grid(row=0, column=2)

        ttk.Label(path_frame, text="目标文件夹:").grid(row=1,
                                                    column=0,
                                                    sticky=tk.W,
                                                    pady=5)
        ttk.Entry(path_frame,
                  textvariable=self.dst_dir,
                  width=50).grid(row=1, column=1, padx=5)
        ttk.Button(path_frame,
                  text="浏览…",
                  command=self.select_dst).grid(row=1, column=2)

        opt_frame = ttk.Frame(path_frame)
        opt_frame.grid(row=2, column=1, sticky=tk.W, pady=5)
        ttk.Checkbutton(opt_frame,
                        text="包含子文件夹",
                        variable=self.recursive).pack(side=tk.LEFT,
                                                   padx=5)
        ttk.Radiobutton(opt_frame,
                         text="移动文件",
                         variable=self.move_files,
                         value=True).pack(side=tk.LEFT,
                                         padx=5)
        ttk.Radiobutton(opt_frame,
                         text="复制文件",
                         variable=self.move_files,
                         value=False).pack(side=tk.LEFT,
                                          padx=5)

        # ---------- 2️⃣ 规则 ----------
        rule_frame = ttk.LabelFrame(self.right_frame,
                                    text="分类规则（顺序匹配，先匹配即止）",
                                    padding="5")
        rule_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # 列表 + 垂直滚动条
        list_frame = ttk.Frame(rule_frame)
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.rule_listbox = tk.Listbox(list_frame, height=8)
        self.rule_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        rule_scroll = ttk.Scrollbar(list_frame,
                                   orient=tk.VERTICAL,
                                   command=self.rule_listbox.yview)
        rule_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.rule_listbox.config(yscrollcommand=rule_scroll.set)

        # 按钮列
        btn_frame = ttk.Frame(rule_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)

        ttk.Button(btn_frame,
                   text="添加规则",
                   command=self.add_rule).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame,
                   text="编辑规则",
                   command=self.edit_rule).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame,
                   text="删除规则",
                   command=self.delete_rule).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame,
                   text="上移",
                   command=self.move_rule_up).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame,
                   text="下移",
                   command=self.move_rule_down).pack(fill=tk.X, pady=2)

        # ---------- 3️⃣ 操作按钮 ----------
        action_frame = ttk.Frame(self.right_frame)
        action_frame.pack(fill=tk.X, pady=5)

        ttk.Button(action_frame,
                   text="预览分类",
                   command=self.preview).pack(side=tk.LEFT,
                                             padx=5)
        ttk.Button(action_frame,
                   text="开始分类",
                   command=self.start_categorize).pack(side=tk.LEFT,
                                                      padx=5)
        ttk.Button(action_frame,
                   text="批量重命名",
                   command=self.bulk_rename).pack(side=tk.LEFT,
                                                  padx=5)
        ttk.Button(action_frame,
                   text="查找重复文件",
                   command=self.find_duplicates).pack(side=tk.LEFT,
                                                      padx=5)
        ttk.Button(action_frame,
                   text="清空日志",
                   command=self.clear_log).pack(side=tk.LEFT,
                                                padx=5)

        # ---------- 4️⃣ 日志 ----------
        log_frame = ttk.LabelFrame(self.right_frame,
                                   text="日志",
                                   padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = tk.Text(log_frame,
                                height=10,
                                wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_scroll = ttk.Scrollbar(log_frame,
                                   orient=tk.VERTICAL,
                                   command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scroll.set)

        # ---------- 5️⃣ 进度条 ----------
        self.progress = ttk.Progressbar(self.right_frame,
                                         orient=tk.HORIZONTAL,
                                         length=100,
                                         mode='determinate')
        self.progress.pack(fill=tk.X, pady=5)

        # ---------- 6️⃣ 状态栏 ----------
        self.status = ttk.Label(self.right_frame,
                               text="就绪",
                               relief=tk.SUNKEN,
                               anchor=tk.W)
        self.status.pack(fill=tk.X, pady=2)

    # --------------------------------------------------------------
    #  通用 UI 辅助（线程安全调用）
    # --------------------------------------------------------------
    def ui_call(self, func, *a, **kw):
        """把函数投递到主线程执行（子线程安全更新 UI）"""
        self.after(0, lambda: func(*a, **kw))

    def log(self, msg: str):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.update_idletasks()

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def update_status(self):
        self.status.config(
            text=f"规则数: {len(self.rules)} | "
                 f"源: {self.src_dir.get() or '未选'} | "
                 f"目标: {self.dst_dir.get() or '未选'}"
        )

    # --------------------------------------------------------------
    #  路径选择
    # --------------------------------------------------------------
    def select_src(self):
        d = filedialog.askdirectory(title="选择源文件夹")
        if d:
            self.src_dir.set(d)
            self.update_status()

    def select_dst(self):
        d = filedialog.askdirectory(title="选择目标文件夹")
        if d:
            self.dst_dir.set(d)
            self.update_status()

    # --------------------------------------------------------------
    #  规则列表相关
    # --------------------------------------------------------------
    def refresh_rule_list(self):
        self.rule_listbox.delete(0, tk.END)
        for r in self.rules:
            self.rule_listbox.insert(tk.END,
                                    f"包含「{r['match']}」 → 放入「{r['folder']}」")
        self.update_status()

    def add_rule(self):
        dlg = RuleDialog(self)
        self.wait_window(dlg)
        if dlg.result is not None:
            match, folder = dlg.result
            self.rules.append({'match': match, 'folder': folder})
            self.refresh_rule_list()
            self.log(f"添加规则: 包含「{match or '<空>'}」 → 「{folder or '<根>'}」")

    def edit_rule(self):
        sel = self.rule_listbox.curselection()
        if not sel:
            messagebox.showwarning("警告", "请先选择一条规则")
            return
        idx = sel[0]
        cur = self.rules[idx]
        dlg = RuleDialog(self, cur['match'], cur['folder'])
        self.wait_window(dlg)
        if dlg.result is not None:
            match, folder = dlg.result
            self.rules[idx] = {'match': match, 'folder': folder}
            self.refresh_rule_list()
            self.log(f"编辑规则: 包含「{match or '<空>'}」 → 「{folder or '<根>'}」")

    def delete_rule(self):
        sel = self.rule_listbox.curselection()
        if not sel:
            messagebox.showwarning("警告", "请先选择一条规则")
            return
        idx = sel[0]
        removed = self.rules.pop(idx)
        self.refresh_rule_list()
        self.log(f"删除规则: 包含「{removed['match'] or '<空>'}」 → 「{removed['folder'] or '<根>'}」")

    def move_rule_up(self):
        sel = self.rule_listbox.curselection()
        if not sel or sel[0] == 0:
            return
        i = sel[0]
        self.rules[i], self.rules[i - 1] = self.rules[i - 1], self.rules[i]
        self.refresh_rule_list()
        self.rule_listbox.selection_set(i - 1)

    def move_rule_down(self):
        sel = self.rule_listbox.curselection()
        if not sel or sel[0] == len(self.rules) - 1:
            return
        i = sel[0]
        self.rules[i], self.rules[i + 1] = self.rules[i + 1], self.rules[i]
        self.refresh_rule_list()
        self.rule_listbox.selection_set(i + 1)

    # --------------------------------------------------------------
    #  文件遍历与匹配
    # --------------------------------------------------------------
    def get_all_files(self):
        src = self.src_dir.get()
        if not os.path.isdir(src):
            return []

        if self.recursive.get():
            files = []
            for root, _, fnames in os.walk(src):
                for f in fnames:
                    files.append(os.path.join(root, f))
            return files
        else:
            return [os.path.join(src, f) for f in os.listdir(src)
                    if os.path.isfile(os.path.join(src, f))]

    def categorize_file(self, filepath):
        """返回目标子文件夹名（空串 = 根目录），若未匹配返回 None"""
        name = os.path.basename(filepath)
        for rule in self.rules:
            if rule['match'] == "" or rule['match'] in name:
                return rule['folder'] if rule['folder'] else ""
        return None

    # --------------------------------------------------------------
    #  预览功能（左侧高频词 + 分类树）
    # --------------------------------------------------------------
    def preview(self):
        """在左侧面板生成高频词列表和分类树"""
        if not self.src_dir.get():
            messagebox.showwarning("警告", "请选择源文件夹")
            return

        files = self.get_all_files()
        if not files:
            self.log("源文件夹中没有文件")
            return

        # ---------- 1️⃣ 高频词统计 ----------
        threshold = max(1, self.freq_threshold.get())
        token_counter = Counter()
        for f in files:
            name, _ = os.path.splitext(os.path.basename(f))
            # 以非字母数字分割（兼容中文、英文、数字混合）
            tokens = re.split(r'\W+', name.lower())
            token_counter.update([t for t in tokens if t and len(t) > 1])

        frequent = [(w, c) for w, c in token_counter.items() if c >= threshold]
        frequent.sort(key=lambda x: (-x[1], x[0]))

        self.freq_listbox.delete(0, tk.END)
        for w, c in frequent:
            self.freq_listbox.insert(tk.END, f"{w} ({c} 次)")

        # ---------- 2️⃣ 分类树 ----------
        self.preview_tree.delete(*self.preview_tree.get_children())
        self._tree_item_path.clear()

        mapping = defaultdict(list)   # folder → [full_path, …]
        for f in files:
            folder = self.categorize_file(f)
            key = folder if folder is not None else "未分类"
            mapping[key].append(f)

        # 按文件夹名排序（根目录放首位）
        ordered_folders = sorted(mapping.keys(),
                                 key=lambda x: (0 if x == "" else 1, x.lower()))
        for folder in ordered_folders:
            display = "<根目录>" if folder == "" else folder
            parent = self.preview_tree.insert("", tk.END,
                                             text=display,
                                             open=True)
            for fpath in sorted(mapping[folder],
                               key=lambda p: os.path.basename(p).lower()):
                fname = os.path.basename(fpath)
                leaf = self.preview_tree.insert(parent,
                                               tk.END,
                                               text=fname,
                                               values=(fpath,))
                self._tree_item_path[leaf] = fpath

        self.log("预览已刷新（左侧面板）")
        self.update_status()

    # --------------------------------------------------------------
    #  双击打开文件（左侧树）
    # --------------------------------------------------------------
    def _on_tree_double_click(self, event):
        """在树中双击文件节点即打开对应的系统程序"""
        item = self.preview_tree.identify('item', event.x, event.y)
        if not item:
            return
        path = self._tree_item_path.get(item)
        if path and os.path.isfile(path):
            self._open_file_system(path)

    def _open_file_system(self, path):
        """跨平台打开文件（Windows / macOS / Linux）"""
        try:
            if sys.platform.startswith('win'):
                os.startfile(path)
            elif sys.platform.startswith('darwin'):
                subprocess.Popen(['open', path])
            else:  # linux / unix
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            self.log(f"❌ 打开失败 {path}: {e}")

    # --------------------------------------------------------------
    #  开始分类（多线程，UI 更新走 ui_call）
    # --------------------------------------------------------------
    def start_categorize(self):
        if not self.src_dir.get() or not self.dst_dir.get():
            messagebox.showwarning("警告", "请先选择源文件夹和目标文件夹")
            return

        files = self.get_all_files()
        if not files:
            self.log("源文件夹中没有文件")
            return

        # 仅保留匹配到规则的文件
        matched = [f for f in files if self.categorize_file(f) is not None]
        if not matched:
            self.log("没有符合规则的文件")
            return

        self.progress['maximum'] = len(matched)
        self.progress['value'] = 0
        threading.Thread(target=self._categorize_thread,
                         args=(matched,),
                         daemon=True).start()

    def _categorize_thread(self, files):
        dst_root = self.dst_dir.get()
        moved_cnt = 0
        error_cnt = 0

        for i, src_path in enumerate(files):
            filename = os.path.basename(src_path)
            subfolder = self.categorize_file(src_path) or "未分类"
            dst_dir = os.path.join(dst_root, subfolder)
            os.makedirs(dst_dir, exist_ok=True)

            dst_path = os.path.join(dst_dir, filename)

            # 处理同名冲突
            if os.path.exists(dst_path):
                base, ext = os.path.splitext(filename)
                n = 1
                while True:
                    new_name = f"{base}_{n}{ext}"
                    new_path = os.path.join(dst_dir, new_name)
                    if not os.path.exists(new_path):
                        dst_path = new_path
                        break
                    n += 1

            try:
                if self.move_files.get():
                    shutil.move(src_path, dst_path)
                    self.ui_call(self.log,
                                 f"移动: {src_path} → {dst_path}")
                else:
                    shutil.copy2(src_path, dst_path)
                    self.ui_call(self.log,
                                 f"复制: {src_path} → {dst_path}")
                moved_cnt += 1
            except Exception as exc:
                self.ui_call(self.log,
                             f"❌ 错误: {src_path} → {exc}")
                error_cnt += 1

            self.ui_call(self.progress.__setitem__, 'value', i + 1)

        self.ui_call(self.log,
                     "\n===== 处理完成 =====")
        self.ui_call(self.log,
                     f"成功: {moved_cnt} 个文件 | 错误: {error_cnt}")
        self.ui_call(self.progress.__setitem__, 'value', 0)
        self.ui_call(self.update_status)

    # --------------------------------------------------------------
    #  附加工具（保持原实现，仅轻微注释）
    # --------------------------------------------------------------
    def bulk_rename(self):
        """批量查找‑替换重命名"""
        folder = filedialog.askdirectory(title="选择要重命名的文件夹")
        if not folder:
            return

        find_str = simpledialog.askstring("查找", "请输入要查找的文本：")
        if find_str is None:
            return
        replace_str = simpledialog.askstring("替换",
                                            "请输入替换为的文本（留空则删除）：")
        if replace_str is None:
            replace_str = ""

        files = [f for f in os.listdir(folder)
                 if os.path.isfile(os.path.join(folder, f))]
        changes = [(f, f.replace(find_str, replace_str))
                   for f in files if find_str in f]

        if not changes:
            messagebox.showinfo("信息", "没有匹配的文件")
            return

        preview = "即将重命名的文件列表：\n\n"
        preview += "\n".join(f"{old} → {new}" for old, new in changes)
        if not messagebox.askyesno("确认重命名", preview):
            return

        for old, new in changes:
            try:
                os.rename(os.path.join(folder, old),
                          os.path.join(folder, new))
                self.log(f"重命名: {old} → {new}")
            except Exception as e:
                self.log(f"❌ 重命名失败 {old}: {e}")

        self.log("批量重命名完成")

    def find_duplicates(self):
        """基于 MD5 的重复文件查找"""
        folder = filedialog.askdirectory(title="选择要查找重复文件的文件夹")
        if not folder:
            return

        self.log("正在计算哈希，请稍候…")
        hash_map = defaultdict(list)
        all_files = []
        for root, _, fs in os.walk(folder):
            for f in fs:
                all_files.append(os.path.join(root, f))

        self.progress['maximum'] = len(all_files)
        self.progress['value'] = 0

        for i, fpath in enumerate(all_files):
            try:
                with open(fpath, "rb") as fp:
                    md5 = hashlib.md5(fp.read()).hexdigest()
                    hash_map[md5].append(fpath)
            except Exception as e:
                self.log(f"读取失败 {fpath}: {e}")
            self.progress['value'] = i + 1
            self.progress.update()

        dup = {h: lst for h, lst in hash_map.items() if len(lst) > 1}
        if not dup:
            self.log("未发现重复文件")
        else:
            self.log(f"共发现 {len(dup)} 组重复文件：")
            for h, lst in dup.items():
                self.log(f"\n哈希 {h}:")
                for p in lst:
                    self.log(f"  {p}")

        self.progress['value'] = 0
        self.update_status()

# --------------------------------------------------------------
# 规则编辑对话框（保持原实现，取消时 result 为 None）
# --------------------------------------------------------------
class RuleDialog(tk.Toplevel):
    def __init__(self, master, match="", folder=""):
        super().__init__(master)
        self.title("规则编辑")
        self.result = None
        self.transient(master)
        self.grab_set()

        ttk.Label(self, text="文件名包含 (留空匹配所有)：").grid(row=0,
                                                                column=0,
                                                                padx=5,
                                                                pady=5,
                                                                sticky=tk.W)
        self.match_entry = ttk.Entry(self, width=30)
        self.match_entry.grid(row=0, column=1, padx=5, pady=5)
        self.match_entry.insert(0, match)

        ttk.Label(self, text="放入子文件夹 (留空放根目录)：").grid(row=1,
                                                                column=0,
                                                                padx=5,
                                                                pady=5,
                                                                sticky=tk.W)
        self.folder_entry = ttk.Entry(self, width=30)
        self.folder_entry.grid(row=1, column=1, padx=5, pady=5)
        self.folder_entry.insert(0, folder)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="确定", command=self.ok).pack(side=tk.LEFT,
                                                               padx=5)
        ttk.Button(btn_frame, text="取消", command=self.cancel).pack(side=tk.LEFT,
                                                                   padx=5)

        # 快捷键
        self.match_entry.bind("<Return>", lambda e: self.folder_entry.focus())
        self.folder_entry.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.cancel())
        self.match_entry.focus()

    def ok(self):
        self.result = (self.match_entry.get().strip(),
                       self.folder_entry.get().strip())
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


# --------------------------------------------------------------
# 程序入口
# --------------------------------------------------------------
if __name__ == "__main__":
    app = FileCategorizerApp()
    app.mainloop()
