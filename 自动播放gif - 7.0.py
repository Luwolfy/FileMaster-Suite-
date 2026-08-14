import tkinter as tk
from tkinter import ttk, filedialog, messagebox, Menu
from PIL import Image, ImageTk
import os
import time
import threading
import math
from collections import namedtuple

GifFrame = namedtuple('GifFrame', ['image', 'duration'])

class GifPlayer:
    CONFIG_FILE = "gif_player_config.txt"

    def __init__(self, root):
        self.root = root
        self.root.title("GIF/图片 自动播放器 Pro Max")
        self.root.geometry("1100x800")
        self.root.minsize(900, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 状态变量
        self.files = []
        self.current_file_index = -1
        self.frames = []
        self.total_duration = 0
        self.completed_duration = 0
        self.current_frame_idx = 0
        self.frame_start_time = 0
        self.playing = False
        self.paused = False
        self.after_id_frame = None
        self.after_id_progress = None
        self.speed = 1.0
        self.play_mode = tk.StringVar(value="loop_all")
        self.show_overlay = tk.BooleanVar(value=True)
        self.seek_dragging = False
        self.was_playing_before_drag = False
        self.fullscreen = False

        # 新增：静态图片停留时间（秒）
        self.image_duration_seconds = tk.DoubleVar(value=3.0)
        self.image_duration_seconds.trace('w', self.on_image_duration_change)

        # 重复模式
        self.repeat_mode = tk.StringVar(value="frames")
        self.rules = []
        self.min_duration_seconds = tk.DoubleVar(value=5.0)

        # 重复播放状态
        self.current_repeat = 0
        self.target_repeat = 1
        self.total_elapsed_ms = 0

        # 收藏列表
        self.favorites = []

        # 缩放缓存
        self.cached_photos = {}
        self.last_canvas_size = (0, 0)
        self.canvas_photo = None
        self.canvas_image_id = None
        self.canvas_text_id = None
        self._resize_after_id = None

        # 后台加载
        self.loader_thread = None
        self.load_lock = threading.Lock()
        self.frames_ready = False
        self.all_frames_loaded = False
        # 预加载队列：最多预加载接下来的两个文件
        self.preloaded = {}           # {index: [GifFrame, ...]}
        self.preloading_indices = set()
        self.pending_play = False

        self.ui_containers = []

        self.setup_style()
        self.create_widgets()
        self.init_default_rules()
        self.load_config()
        self.update_repeat_ui()
        self.create_menu()
        self.bind_shortcuts()
        self.save_config()

    def setup_style(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', padding=6, font=('Segoe UI', 9))
        style.configure('TLabel', font=('Segoe UI', 9))
        style.configure('TLabelframe.Label', font=('Segoe UI', 9, 'bold'))

    def init_default_rules(self):
        self.rules = [(1, 10, 6), (11, 26, 4), (27, 35, 2)]
        self.update_rule_listbox()

    # ---------- 配置 ----------
    def get_config_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), self.CONFIG_FILE)

    def save_config(self):
        path = self.get_config_path()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f"repeat_mode={self.repeat_mode.get()}\n")
                f.write(f"min_duration_seconds={self.min_duration_seconds.get()}\n")
                f.write(f"play_mode={self.play_mode.get()}\n")
                f.write(f"show_overlay={self.show_overlay.get()}\n")
                f.write(f"speed={self.speed_var.get()}\n")
                f.write(f"recursive={self.recursive_var.get()}\n")
                f.write(f"image_duration_seconds={self.image_duration_seconds.get()}\n")
                for min_f, max_f, times in self.rules:
                    f.write(f"rule={min_f},{max_f},{times}\n")
                for fav in self.favorites:
                    f.write(f"favorite={fav}\n")
        except Exception as e:
            print(f"保存配置失败: {e}")

    def load_config(self):
        path = self.get_config_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.rules = []
                self.favorites = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if '=' in line and not line.startswith('rule=') and not line.startswith('favorite='):
                        key, val = line.split('=', 1)
                        key = key.strip()
                        val = val.strip()
                        if key == 'repeat_mode':
                            self.repeat_mode.set(val)
                        elif key == 'min_duration_seconds':
                            self.min_duration_seconds.set(float(val))
                        elif key == 'play_mode':
                            self.play_mode.set(val)
                        elif key == 'show_overlay':
                            self.show_overlay.set(val.lower() == 'true')
                        elif key == 'speed':
                            self.speed_var.set(float(val))
                        elif key == 'recursive':
                            self.recursive_var.set(val.lower() == 'true')
                        elif key == 'image_duration_seconds':
                            self.image_duration_seconds.set(float(val))
                    elif line.startswith('rule='):
                        parts = line[5:].split(',')
                        if len(parts) == 3:
                            min_f, max_f, times = map(int, parts)
                            self.rules.append((min_f, max_f, times))
                    elif line.startswith('favorite='):
                        fav_path = line[9:].strip()
                        if os.path.exists(fav_path):
                            self.favorites.append(fav_path)
                if not self.rules:
                    self.init_default_rules()
                self.update_rule_listbox()
        except Exception as e:
            print(f"加载配置失败: {e}")

    def on_setting_changed(self, *args):
        self.save_config()

    # ---------- UI ----------
    def create_menu(self):
        self.menubar = Menu(self.root)
        self.root.config(menu=self.menubar)

        file_menu = Menu(self.menubar, tearoff=0)
        file_menu.add_command(label="添加文件夹...", command=self.add_folder, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="清空列表", command=self.clear_list)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.on_closing)
        self.menubar.add_cascade(label="文件", menu=file_menu)

        view_menu = Menu(self.menubar, tearoff=0)
        view_menu.add_checkbutton(label="显示帧/时间叠加", variable=self.show_overlay, command=self.on_overlay_toggle)
        view_menu.add_separator()
        view_menu.add_command(label="切换全屏", command=self.toggle_fullscreen, accelerator="F11")
        self.menubar.add_cascade(label="视图", menu=view_menu)

        fav_menu = Menu(self.menubar, tearoff=0)
        fav_menu.add_command(label="收藏/取消当前 (Ctrl+F)", command=self.toggle_favorite)
        fav_menu.add_command(label="管理收藏...", command=self.manage_favorites)
        self.menubar.add_cascade(label="收藏", menu=fav_menu)

    def on_overlay_toggle(self):
        self.update_overlay_visibility()
        self.save_config()

    def create_widgets(self):
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=0)
        self.root.grid_columnconfigure(0, weight=1)

        control_outer = ttk.Frame(self.root)
        control_outer.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        control_frame = ttk.Frame(control_outer)
        control_frame.pack(fill=tk.X, pady=2)

        btn_frame = ttk.Frame(control_frame)
        btn_frame.pack(side=tk.LEFT)
        self.add_btn = ttk.Button(btn_frame, text="添加文件夹", command=self.add_folder)
        self.add_btn.pack(side=tk.LEFT, padx=2)
        self.recursive_var = tk.BooleanVar(value=True)
        self.recursive_var.trace('w', self.on_setting_changed)
        ttk.Checkbutton(btn_frame, text="包含子文件夹", variable=self.recursive_var).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清空", command=self.clear_list).pack(side=tk.LEFT, padx=2)

        ttk.Separator(control_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        play_frame = ttk.Frame(control_frame)
        play_frame.pack(side=tk.LEFT)
        ttk.Button(play_frame, text="◀◀", width=3, command=self.prev_file).pack(side=tk.LEFT, padx=1)
        self.play_pause_btn = ttk.Button(play_frame, text="▶ 播放", width=6, command=self.toggle_play_pause)
        self.play_pause_btn.pack(side=tk.LEFT, padx=1)
        ttk.Button(play_frame, text="▶▶", width=3, command=self.next_file).pack(side=tk.LEFT, padx=1)
        ttk.Button(play_frame, text="■ 停止", width=6, command=self.stop).pack(side=tk.LEFT, padx=1)

        ttk.Separator(control_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        mode_frame = ttk.Frame(control_frame)
        mode_frame.pack(side=tk.LEFT)
        ttk.Label(mode_frame, text="模式:").pack(side=tk.LEFT)
        mode_menu = ttk.OptionMenu(mode_frame, self.play_mode, "loop_all",
                                   "loop_all", "sequential", "single_loop", "single_once",
                                   command=self.on_mode_change)
        mode_menu.pack(side=tk.LEFT, padx=2)
        self.mode_text = {"loop_all": "全部循环", "sequential": "顺序播放",
                          "single_loop": "单曲循环", "single_once": "单曲一次"}
        self.mode_label = ttk.Label(mode_frame, text="全部循环")
        self.mode_label.pack(side=tk.LEFT, padx=2)
        self.play_mode.trace('w', lambda *args: self.mode_label.config(text=self.mode_text.get(self.play_mode.get(), "")))
        self.play_mode.trace('w', self.on_setting_changed)

        ttk.Separator(control_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        speed_frame = ttk.Frame(control_frame)
        speed_frame.pack(side=tk.LEFT)
        ttk.Label(speed_frame, text="速度:").pack(side=tk.LEFT)
        self.speed_var = tk.DoubleVar(value=1.0)
        speed_scale = ttk.Scale(speed_frame, from_=0.25, to=4.0, orient=tk.HORIZONTAL,
                                variable=self.speed_var, length=100, command=self.on_speed_change)
        speed_scale.pack(side=tk.LEFT, padx=2)
        self.speed_label = ttk.Label(speed_frame, text="1.0x")
        self.speed_label.pack(side=tk.LEFT, padx=2)
        self.speed_var.trace('w', lambda *args: self.speed_label.config(text=f"{self.speed_var.get():.1f}x"))
        self.speed_var.trace('w', self.on_setting_changed)

        # 新增：图片停留时间设置
        img_dur_frame = ttk.Frame(control_frame)
        img_dur_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(img_dur_frame, text="图片停留:").pack(side=tk.LEFT)
        self.img_duration_entry = ttk.Entry(img_dur_frame, width=5, textvariable=self.image_duration_seconds)
        self.img_duration_entry.pack(side=tk.LEFT, padx=2)
        ttk.Label(img_dur_frame, text="秒").pack(side=tk.LEFT)

        ttk.Separator(control_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        jump_frame = ttk.Frame(control_frame)
        jump_frame.pack(side=tk.RIGHT, padx=5)
        ttk.Label(jump_frame, text="跳转到第").pack(side=tk.LEFT)
        self.jump_entry = ttk.Entry(jump_frame, width=6)
        self.jump_entry.pack(side=tk.LEFT, padx=2)
        ttk.Button(jump_frame, text="跳转", command=self.jump_to_file).pack(side=tk.LEFT, padx=2)
        self.jump_entry.bind("<Return>", lambda e: self.jump_to_file())

        self.fullscreen_btn = ttk.Button(control_frame, text="⛶ 全屏", command=self.toggle_fullscreen)
        self.fullscreen_btn.pack(side=tk.RIGHT, padx=5)

        # 重复设置
        repeat_outer = ttk.LabelFrame(control_outer, text="重复播放设置", padding=5)
        repeat_outer.pack(fill=tk.X, pady=(5,0))

        repeat_mode_frame = ttk.Frame(repeat_outer)
        repeat_mode_frame.pack(fill=tk.X, pady=2)

        ttk.Radiobutton(repeat_mode_frame, text="按帧数区间", variable=self.repeat_mode, value="frames",
                        command=self.on_repeat_mode_change).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(repeat_mode_frame, text="按时间长度", variable=self.repeat_mode, value="duration",
                        command=self.on_repeat_mode_change).pack(side=tk.LEFT, padx=5)

        self.frames_rules_frame = ttk.Frame(repeat_outer)
        rule_edit_frame = ttk.Frame(self.frames_rules_frame)
        rule_edit_frame.pack(fill=tk.X, pady=2)

        ttk.Label(rule_edit_frame, text="最小帧:").pack(side=tk.LEFT)
        self.min_frame_entry = ttk.Entry(rule_edit_frame, width=6)
        self.min_frame_entry.pack(side=tk.LEFT, padx=2)

        ttk.Label(rule_edit_frame, text="最大帧:").pack(side=tk.LEFT)
        self.max_frame_entry = ttk.Entry(rule_edit_frame, width=6)
        self.max_frame_entry.pack(side=tk.LEFT, padx=2)

        ttk.Label(rule_edit_frame, text="重复次数:").pack(side=tk.LEFT)
        self.repeat_entry = ttk.Entry(rule_edit_frame, width=6)
        self.repeat_entry.pack(side=tk.LEFT, padx=2)

        ttk.Button(rule_edit_frame, text="添加规则", command=self.add_rule).pack(side=tk.LEFT, padx=5)
        ttk.Button(rule_edit_frame, text="删除选中", command=self.delete_rule).pack(side=tk.LEFT, padx=2)

        list_scroll = ttk.Scrollbar(self.frames_rules_frame)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.rule_listbox = tk.Listbox(self.frames_rules_frame, height=4, yscrollcommand=list_scroll.set)
        self.rule_listbox.pack(fill=tk.X, expand=True, pady=2)
        list_scroll.config(command=self.rule_listbox.yview)

        self.duration_rules_frame = ttk.Frame(repeat_outer)
        ttk.Label(self.duration_rules_frame, text="最少播放秒数:").pack(side=tk.LEFT, padx=5)
        self.duration_entry = ttk.Entry(self.duration_rules_frame, width=6, textvariable=self.min_duration_seconds)
        self.duration_entry.pack(side=tk.LEFT, padx=2)
        self.min_duration_seconds.trace('w', self.on_setting_changed)

        # Canvas
        self.canvas = tk.Canvas(self.root, bg="black", bd=0, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.canvas.bind("<Button-3>", self.show_context_menu)
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_checkbutton(label="显示帧/时间叠加", variable=self.show_overlay,
                                          command=self.on_overlay_toggle)

        # 底部进度区
        bottom_frame = ttk.Frame(self.root, padding=5)
        bottom_frame.grid(row=2, column=0, sticky="ew")

        seek_frame = ttk.Frame(bottom_frame)
        seek_frame.pack(fill=tk.X, pady=2)
        ttk.Label(seek_frame, text="进度:").pack(side=tk.LEFT)
        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_scale = ttk.Scale(seek_frame, from_=0.0, to=100.0, orient=tk.HORIZONTAL,
                                    variable=self.seek_var, length=500, command=self.on_seek_drag)
        self.seek_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.seek_scale.bind("<ButtonPress-1>", self.on_seek_press)
        self.seek_scale.bind("<ButtonRelease-1>", self.on_seek_release)
        self.time_label = ttk.Label(seek_frame, text="00:00 / 00:00")
        self.time_label.pack(side=tk.LEFT, padx=5)

        list_prog_frame = ttk.Frame(bottom_frame)
        list_prog_frame.pack(fill=tk.X, pady=2)
        ttk.Label(list_prog_frame, text="列表:").pack(side=tk.LEFT)
        self.total_progress = ttk.Progressbar(list_prog_frame, orient=tk.HORIZONTAL, mode='determinate', length=300)
        self.total_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.file_count_label = ttk.Label(list_prog_frame, text="0/0")
        self.file_count_label.pack(side=tk.LEFT, padx=5)
        self.info_label = ttk.Label(list_prog_frame, text="未添加文件", anchor=tk.W)
        self.info_label.pack(side=tk.LEFT, padx=10)

        list_frame = ttk.LabelFrame(self.root, text="播放列表", padding=5)
        list_frame.grid(row=3, column=0, sticky="ew", padx=5, pady=(0,5))
        list_frame.columnconfigure(0, weight=1)
        list_scroll2 = ttk.Scrollbar(list_frame)
        list_scroll2.grid(row=0, column=1, sticky="ns")
        self.file_listbox = tk.Listbox(list_frame, height=6, yscrollcommand=list_scroll2.set)
        self.file_listbox.grid(row=0, column=0, sticky="nsew")
        list_scroll2.config(command=self.file_listbox.yview)
        self.file_listbox.bind('<<ListboxSelect>>', self.on_list_select)

        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=2)
        status_bar.grid(row=4, column=0, sticky="ew")

        self.ui_containers = [control_outer, bottom_frame, list_frame, status_bar]

    # ---------- 收藏功能 ----------
    def toggle_favorite(self, event=None):
        if self.current_file_index < 0 or not self.files:
            messagebox.showinfo("提示", "没有打开的文件")
            return
        current_path = self.files[self.current_file_index]
        if current_path in self.favorites:
            self.favorites.remove(current_path)
            self.status_var.set(f"已取消收藏: {os.path.basename(current_path)}")
        else:
            self.favorites.append(current_path)
            self.status_var.set(f"已收藏: {os.path.basename(current_path)}")
        self.save_config()

    def manage_favorites(self):
        if not self.favorites:
            messagebox.showinfo("收藏夹", "收藏夹为空")
            return
        fav_win = tk.Toplevel(self.root)
        fav_win.title("收藏夹")
        fav_win.geometry("500x400")
        fav_win.minsize(300, 200)

        fav_frame = ttk.Frame(fav_win, padding=5)
        fav_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(fav_frame, text="双击列表项播放，右键删除", font=('Segoe UI', 9)).pack(anchor=tk.W)

        list_frame = ttk.Frame(fav_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        fav_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set)
        fav_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=fav_listbox.yview)

        for path in self.favorites:
            fav_listbox.insert(tk.END, os.path.basename(path))

        def on_double_click(event):
            selection = fav_listbox.curselection()
            if selection:
                idx = selection[0]
                if idx < len(self.favorites):
                    path = self.favorites[idx]
                    if path in self.files:
                        file_idx = self.files.index(path)
                        self.select_file(file_idx, auto_play=True)
                    else:
                        messagebox.showinfo("提示", "该文件不在当前播放列表中")
        fav_listbox.bind("<Double-Button-1>", on_double_click)

        def on_right_click(event):
            selection = fav_listbox.curselection()
            if selection:
                idx = selection[0]
                if idx < len(self.favorites):
                    path = self.favorites[idx]
                    confirm = messagebox.askyesno("确认", f"确定从收藏夹移除 {os.path.basename(path)} 吗？")
                    if confirm:
                        self.favorites.remove(path)
                        fav_listbox.delete(idx)
                        self.save_config()
        fav_listbox.bind("<Button-3>", on_right_click)

    # ---------- 规则管理 ----------
    def add_rule(self):
        try:
            min_f = int(self.min_frame_entry.get().strip())
            max_f = int(self.max_frame_entry.get().strip())
            times = int(self.repeat_entry.get().strip())
        except ValueError:
            messagebox.showerror("错误", "请输入有效的整数。")
            return
        if min_f < 1 or max_f < min_f or times < 1:
            messagebox.showerror("错误", "最小帧≥1，最大帧≥最小帧，重复次数≥1。")
            return
        self.rules.append((min_f, max_f, times))
        self.update_rule_listbox()
        self.min_frame_entry.delete(0, tk.END)
        self.max_frame_entry.delete(0, tk.END)
        self.repeat_entry.delete(0, tk.END)
        self.on_setting_changed()
        self.update_target_and_reset()

    def delete_rule(self):
        selection = self.rule_listbox.curselection()
        if selection:
            index = selection[0]
            del self.rules[index]
            self.update_rule_listbox()
            self.on_setting_changed()
            self.update_target_and_reset()

    def update_rule_listbox(self):
        self.rule_listbox.delete(0, tk.END)
        for min_f, max_f, times in self.rules:
            self.rule_listbox.insert(tk.END, f"{min_f}-{max_f} 帧 → 重复 {times} 次")

    def update_repeat_ui(self):
        if self.repeat_mode.get() == "frames":
            self.frames_rules_frame.pack(fill=tk.X, pady=2)
            self.duration_rules_frame.pack_forget()
        else:
            self.frames_rules_frame.pack_forget()
            self.duration_rules_frame.pack(fill=tk.X, pady=2)

    def calculate_target_repeat_frames(self):
        if not self.frames:
            return 1
        frame_count = len(self.frames)
        for min_f, max_f, times in self.rules:
            if min_f <= frame_count <= max_f:
                return times
        return 1

    def update_target_and_reset(self):
        if self.repeat_mode.get() == "frames":
            self.target_repeat = self.calculate_target_repeat_frames()
        else:
            self.target_repeat = 0
        self.current_repeat = 0
        self.total_elapsed_ms = 0
        if self.playing:
            self._update_overlay_text()

    def on_repeat_mode_change(self):
        self.update_repeat_ui()
        self.update_target_and_reset()
        self.save_config()

    # ---------- 全屏 ----------
    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            for widget in self.ui_containers:
                widget.grid_remove()
            self.root.config(menu=None)
            self.root.attributes('-fullscreen', True)
            self.canvas.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
            self.root.grid_rowconfigure(0, weight=1)
            self.root.grid_rowconfigure(1, weight=0)
            self.root.grid_rowconfigure(2, weight=0)
        else:
            self.root.attributes('-fullscreen', False)
            self.create_menu()
            for widget in self.ui_containers:
                widget.grid()
            self.canvas.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
            self.root.grid_rowconfigure(0, weight=0)
            self.root.grid_rowconfigure(1, weight=1)
            self.root.grid_rowconfigure(2, weight=0)
            self.fullscreen_btn.config(text="⛶ 全屏")
        self.cached_photos.clear()
        self._refresh_frame()

    def exit_fullscreen_event(self, event=None):
        if self.fullscreen:
            self.toggle_fullscreen()

    # ---------- 文件夹管理 ----------
    def add_folder(self):
        folder = filedialog.askdirectory(title="选择包含GIF/图片的文件夹")
        if not folder:
            return
        new_files = self.scan_folder(folder, self.recursive_var.get())
        if not new_files:
            messagebox.showinfo("提示", "未找到支持的图片文件")
            return
        start_index = len(self.files)
        self.files.extend(new_files)
        for f in new_files:
            self.file_listbox.insert(tk.END, os.path.basename(f))
        self.info_label.config(text=f"已加载 {len(self.files)} 个文件")
        if start_index == 0 and self.files:
            self.select_file(0)
        self._update_total_progress()
        self.status_var.set(f"添加了 {len(new_files)} 个文件")

    def scan_folder(self, folder, recursive):
        image_exts = ('.gif', '.png', '.jpg', '.jpeg', '.bmp', '.webp')
        found_files = []
        if recursive:
            for root, dirs, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(image_exts):
                        found_files.append(os.path.join(root, f))
        else:
            for f in os.listdir(folder):
                if f.lower().endswith(image_exts):
                    found_files.append(os.path.join(folder, f))
        found_files.sort()
        return found_files

    def clear_list(self):
        self.stop()
        self.files = []
        self.file_listbox.delete(0, tk.END)
        self.current_file_index = -1
        self.frames = []
        self.cached_photos.clear()
        self.preloaded.clear()
        self.canvas.delete("all")
        self.canvas_image_id = None
        self.canvas_text_id = None
        self.canvas_photo = None
        self._update_total_progress()
        self.info_label.config(text="未添加文件")
        self.status_var.set("列表已清空")

    def jump_to_file(self):
        if not self.files:
            messagebox.showinfo("提示", "播放列表为空")
            return
        try:
            num = int(self.jump_entry.get().strip())
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
            return
        if num < 1 or num > len(self.files):
            messagebox.showerror("错误", f"序号超出范围，当前共 {len(self.files)} 个文件")
            return
        was_playing = self.playing and not self.paused
        self.select_file(num - 1, auto_play=was_playing)

    def on_list_select(self, event):
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
            if idx != self.current_file_index:
                self.select_file(idx, auto_play=False)

    def select_file(self, index, auto_play=False):
        if not self.files or index < 0 or index >= len(self.files):
            return
        self._stop_playback(keep_selection=False)
        self.current_file_index = index
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(index)
        self.file_listbox.see(index)

        # 使用预加载数据
        if index in self.preloaded:
            self.frames = self.preloaded.pop(index)
            self.total_duration = sum(f.duration for f in self.frames if f)
            self.frames_ready = True
            self.all_frames_loaded = True
            self.current_frame_idx = 0
            self.completed_duration = 0
            self.total_elapsed_ms = 0
            self.cached_photos.clear()
            self.last_canvas_size = (0, 0)
            if self.repeat_mode.get() == "frames":
                self.target_repeat = self.calculate_target_repeat_frames()
            else:
                self.target_repeat = 0
            self.current_repeat = 0
            self._show_frame(0)
            self._update_total_progress()
            self._update_seekbar(0)
            self.info_label.config(text=f"当前: {os.path.basename(self.files[index])}")
            if auto_play:
                self._play_current_file(from_beginning=True)
            else:
                self.status_var.set("就绪，点击播放")
            self.preload_upcoming_files()
            return

        # 后台加载
        self.frames_ready = False
        self.all_frames_loaded = False
        self.frames = []
        self.total_duration = 0
        self.cached_photos.clear()
        self.last_canvas_size = (0, 0)
        self.status_var.set("加载中...")
        self.info_label.config(text=f"加载: {os.path.basename(self.files[index])}")
        self._update_total_progress()
        self.pending_play = auto_play

        path = self.files[index]
        self.loader_thread = threading.Thread(target=self._load_frames_stream, args=(path, index), daemon=True)
        self.loader_thread.start()
        self.root.after(50, self.check_first_frame)

    def _load_frames_stream(self, path, index):
        try:
            if path.lower().endswith('.gif'):
                # 原GIF多帧加载逻辑
                img = Image.open(path)
                n_frames = getattr(img, 'n_frames', 1)
                frames = [None] * n_frames
                total_duration = 0
                for i in range(n_frames):
                    img.seek(i)
                    frame_img = img.copy().convert('RGBA')
                    bg = Image.new('RGBA', frame_img.size, (255, 255, 255, 255))
                    composite = Image.alpha_composite(bg, frame_img)
                    duration = img.info.get('duration', 100)
                    if duration < 20:
                        duration = 100
                    frames[i] = GifFrame(composite, duration)
                    total_duration += duration
                    if i == 0:
                        with self.load_lock:
                            if self.current_file_index == index:
                                self.frames = frames
                                self.total_duration = total_duration
                                self.frames_ready = True
                with self.load_lock:
                    if self.current_file_index == index:
                        self.frames = frames
                        self.total_duration = total_duration
                        self.all_frames_loaded = True
            else:
                # 静态图片：加载为单帧
                img = Image.open(path)
                frame_img = img.convert('RGBA')
                bg = Image.new('RGBA', frame_img.size, (255, 255, 255, 255))
                composite = Image.alpha_composite(bg, frame_img)
                duration = int(self.image_duration_seconds.get() * 1000)
                if duration < 20:
                    duration = 100
                frames = [GifFrame(composite, duration)]
                total_duration = duration
                with self.load_lock:
                    if self.current_file_index == index:
                        self.frames = frames
                        self.total_duration = total_duration
                        self.frames_ready = True
                        self.all_frames_loaded = True
        except Exception as e:
            with self.load_lock:
                self.frames = []
                self.total_duration = 0
                self.frames_ready = True
                self.all_frames_loaded = True
                self.load_error = str(e)

    def check_first_frame(self):
        if not self.frames_ready and self.loader_thread and self.loader_thread.is_alive():
            self.root.after(50, self.check_first_frame)
            return
        if hasattr(self, 'load_error'):
            messagebox.showerror("错误", f"无法加载文件: {self.load_error}")
            del self.load_error
            return
        if not self.frames:
            self.status_var.set("加载失败")
            return

        self.current_frame_idx = 0
        self.completed_duration = 0
        self.total_elapsed_ms = 0
        if self.repeat_mode.get() == "frames":
            self.target_repeat = self.calculate_target_repeat_frames()
        else:
            self.target_repeat = 0
        self.current_repeat = 0
        self._show_frame(0)
        self._update_seekbar(0)
        self.info_label.config(text=f"当前: {os.path.basename(self.files[self.current_file_index])}")

        if self.pending_play:
            self.pending_play = False
            self._play_current_file(from_beginning=True)
        else:
            self.status_var.set("就绪，点击播放")

        self.preload_upcoming_files()
        self.root.after(200, self.check_remaining_frames)

    def check_remaining_frames(self):
        if self.all_frames_loaded:
            self.preload_upcoming_files()
            return
        self.root.after(200, self.check_remaining_frames)

    # ---------- 预加载接下来两个文件 ----------
    def preload_upcoming_files(self):
        """后台预加载接下来的两个文件（如果尚未预加载）"""
        if len(self.files) <= 1:
            return
        indices_to_preload = []
        mode = self.play_mode.get()
        current = self.current_file_index

        def next_idx(curr):
            if mode == "single_once" or mode == "single_loop":
                return None  # 不会自动切换
            elif mode == "sequential":
                nxt = curr + 1
                return nxt if nxt < len(self.files) else None
            elif mode == "loop_all":
                nxt = curr + 1
                return nxt if nxt < len(self.files) else 0
            return None

        idx1 = next_idx(current)
        if idx1 is not None and idx1 not in self.preloaded and idx1 not in self.preloading_indices:
            indices_to_preload.append(idx1)
            if len(self.files) > 2:
                idx2 = next_idx(idx1)
                if idx2 is not None and idx2 != idx1 and idx2 not in self.preloaded and idx2 not in self.preloading_indices:
                    indices_to_preload.append(idx2)

        for idx in indices_to_preload:
            self.preloading_indices.add(idx)
            path = self.files[idx]
            threading.Thread(target=self._preload_bg, args=(path, idx), daemon=True).start()

    def _preload_bg(self, path, index):
        try:
            if path.lower().endswith('.gif'):
                img = Image.open(path)
                n_frames = getattr(img, 'n_frames', 1)
                frames = []
                for i in range(n_frames):
                    img.seek(i)
                    frame_img = img.copy().convert('RGBA')
                    bg = Image.new('RGBA', frame_img.size, (255, 255, 255, 255))
                    composite = Image.alpha_composite(bg, frame_img)
                    duration = img.info.get('duration', 100)
                    if duration < 20:
                        duration = 100
                    frames.append(GifFrame(composite, duration))
                self.preloaded[index] = frames
            else:
                img = Image.open(path)
                frame_img = img.convert('RGBA')
                bg = Image.new('RGBA', frame_img.size, (255, 255, 255, 255))
                composite = Image.alpha_composite(bg, frame_img)
                duration = int(self.image_duration_seconds.get() * 1000)
                if duration < 20:
                    duration = 100
                self.preloaded[index] = [GifFrame(composite, duration)]
        except:
            pass
        finally:
            self.preloading_indices.discard(index)

    # ---------- 画面显示（异步预取）----------
    def _get_scaled_photo(self, idx):
        canvas_w = self.canvas.winfo_width() or 400
        canvas_h = self.canvas.winfo_height() or 300
        if (canvas_w, canvas_h) != self.last_canvas_size:
            self.cached_photos.clear()
            self.last_canvas_size = (canvas_w, canvas_h)

        if idx in self.cached_photos:
            return self.cached_photos[idx]

        frame = self.frames[idx]
        if frame is None:
            for i in range(idx, -1, -1):
                if self.frames[i] is not None:
                    frame = self.frames[i]
                    idx = i
                    break
            if frame is None:
                return None

        img_w, img_h = frame.image.size
        scale = min((canvas_w - 4) / img_w, (canvas_h - 4) / img_h, 1.0)
        new_w = max(1, int(img_w * scale))
        new_h = max(1, int(img_h * scale))
        resized = frame.image.resize((new_w, new_h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(resized)
        self.cached_photos[idx] = photo
        if len(self.cached_photos) > 200:
            oldest = next(iter(self.cached_photos))
            del self.cached_photos[oldest]
        return photo

    def _prefetch_next_frames(self, current_idx):
        """异步预取后续帧，避免阻塞主线程"""
        if not self.frames or not self.all_frames_loaded:
            return
        for offset in range(1, 6):
            next_idx = (current_idx + offset) % len(self.frames)
            if next_idx not in self.cached_photos and self.frames[next_idx] is not None:
                self.root.after(0, lambda idx=next_idx: self._get_scaled_photo(idx))

    def _show_frame(self, idx):
        if not self.frames:
            return
        if self.frames[idx] is None:
            for i in range(idx, -1, -1):
                if self.frames[i] is not None:
                    idx = i
                    break
            else:
                return
        idx = max(0, min(idx, len(self.frames) - 1))
        self.current_frame_idx = idx

        photo = self._get_scaled_photo(idx)
        if photo is None:
            return

        self.canvas_photo = photo
        canvas_w = self.canvas.winfo_width() or 400
        canvas_h = self.canvas.winfo_height() or 300
        if self.canvas_image_id is None:
            self.canvas_image_id = self.canvas.create_image(
                (canvas_w - photo.width()) // 2, (canvas_h - photo.height()) // 2,
                anchor=tk.NW, image=photo)
        else:
            self.canvas.coords(self.canvas_image_id,
                               (canvas_w - photo.width()) // 2, (canvas_h - photo.height()) // 2)
            self.canvas.itemconfig(self.canvas_image_id, image=photo)
        self._update_overlay_text()
        self.root.update_idletasks()
        self._prefetch_next_frames(self.current_frame_idx)

    def on_canvas_resize(self, event):
        if self._resize_after_id:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(150, self._refresh_frame)

    def _refresh_frame(self):
        if self.frames and self.current_frame_idx >= 0:
            self.cached_photos.clear()
            self._show_frame(self.current_frame_idx)

    def _update_overlay_text(self):
        if not self.frames:
            return
        if self.show_overlay.get():
            current_sec = int(self.completed_duration / 1000)
            total_sec = int(self.total_duration / 1000) if self.total_duration > 0 else 0
            if self.repeat_mode.get() == "duration" and self.total_duration > 0:
                total_elapsed_sec = self.total_elapsed_ms / 1000.0
                target_sec = self.min_duration_seconds.get()
                text = (f"累计: {total_elapsed_sec:.1f}s / 目标: {target_sec:.1f}s   "
                        f"帧: {self.current_frame_idx + 1}/{len(self.frames)}")
            else:
                repeat_info = ""
                if self.repeat_mode.get() == "frames" and self.target_repeat > 1:
                    repeat_info = f"  重复:{self.current_repeat+1}/{self.target_repeat}"
                text = (f"帧: {self.current_frame_idx + 1}/{len(self.frames)}  时间: {current_sec//60:02d}:{current_sec%60:02d}"
                        f" / {total_sec//60:02d}:{total_sec%60:02d}{repeat_info}")
            if self.canvas_text_id is None:
                self.canvas_text_id = self.canvas.create_text(8, 8, anchor=tk.NW, text=text,
                                                              fill="yellow", font=("TkDefaultFont", 10, "bold"))
            else:
                self.canvas.itemconfig(self.canvas_text_id, text=text)
        else:
            if self.canvas_text_id:
                self.canvas.itemconfig(self.canvas_text_id, text="")

    def update_overlay_visibility(self):
        self._update_overlay_text()

    def show_context_menu(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    # ---------- 进度条 ----------
    def _update_seekbar(self, elapsed_original):
        if self.total_duration > 0:
            percent = min(100.0, (elapsed_original / self.total_duration) * 100.0)
        else:
            percent = 0.0
        self.seek_var.set(percent)
        current_sec = int(elapsed_original / 1000)
        total_sec = int(self.total_duration / 1000)
        self.time_label.config(text=f"{current_sec//60:02d}:{current_sec%60:02d} / {total_sec//60:02d}:{total_sec%60:02d}")

    def _get_elapsed_original(self):
        if not self.frames:
            return 0
        if self.playing and not self.paused:
            elapsed = self.completed_duration + (time.time() - self.frame_start_time) * self.speed * 1000
        else:
            elapsed = self.completed_duration
        return min(elapsed, self.total_duration)

    def _progress_loop(self):
        if self.playing and not self.paused and not self.seek_dragging:
            elapsed = self._get_elapsed_original()
            self._update_seekbar(elapsed)
            self.after_id_progress = self.root.after(100, self._progress_loop)
        else:
            self.after_id_progress = None

    def on_seek_press(self, event):
        self.seek_dragging = True
        if self.playing and not self.paused:
            self._pause(keep_state=True)
            self.was_playing_before_drag = True
        else:
            self.was_playing_before_drag = False

    def on_seek_release(self, event):
        self.seek_dragging = False
        percent = self.seek_var.get()
        target_time = (percent / 100.0) * self.total_duration
        self._seek_to(target_time)
        if self.was_playing_before_drag:
            self._play_current_file(from_beginning=False)
        else:
            self._show_frame(self.current_frame_idx)
            self._update_seekbar(self.completed_duration)

    def on_seek_drag(self, value):
        if not self.frames or self.total_duration == 0:
            return
        percent = float(value)
        target_time = (percent / 100.0) * self.total_duration
        idx, completed = self._find_frame_at(target_time)
        self.current_frame_idx = idx
        self.completed_duration = completed
        self._show_frame(idx)
        self._update_seekbar(completed)

    def _find_frame_at(self, target_ms):
        cumulative = 0
        for i, frame in enumerate(self.frames):
            if frame is None:
                continue
            if cumulative + frame.duration > target_ms:
                return i, cumulative
            cumulative += frame.duration
        return len(self.frames) - 1, self.total_duration

    def _seek_to(self, target_ms):
        if not self.frames:
            return
        idx, completed = self._find_frame_at(target_ms)
        self.current_frame_idx = idx
        self.completed_duration = completed
        self._show_frame(idx)
        self._update_seekbar(completed)

    def _update_total_progress(self):
        if self.files:
            self.total_progress['maximum'] = len(self.files)
            self.total_progress['value'] = self.current_file_index + 1 if self.current_file_index >= 0 else 0
            self.file_count_label.config(text=f"{self.current_file_index + 1}/{len(self.files)}")
        else:
            self.total_progress['value'] = 0
            self.file_count_label.config(text="0/0")

    # ---------- 播放引擎 ----------
    def _play_current_file(self, from_beginning=False):
        if not self.frames or not self.frames_ready:
            return
        if from_beginning:
            self.current_frame_idx = 0
            self.completed_duration = 0
        if self.after_id_frame:
            self.root.after_cancel(self.after_id_frame)
        self.playing = True
        self.paused = False
        self.frame_start_time = time.time()
        self._show_frame(self.current_frame_idx)
        self._schedule_next_frame()
        if self.after_id_progress:
            self.root.after_cancel(self.after_id_progress)
        self._progress_loop()
        self.play_pause_btn.config(text="⏸ 暂停")
        status_text = "播放中..."
        if self.repeat_mode.get() == "frames" and self.target_repeat > 1:
            status_text += f" (重复 {self.current_repeat+1}/{self.target_repeat})"
        elif self.repeat_mode.get() == "duration":
            target_sec = self.min_duration_seconds.get()
            current_total_sec = self.total_elapsed_ms / 1000.0
            status_text += f" (已播 {current_total_sec:.1f}s / 目标 {target_sec}s)"
        self.status_var.set(status_text)
        self._update_total_progress()
        self.info_label.config(text=f"当前: {os.path.basename(self.files[self.current_file_index])}")
        self.preload_upcoming_files()

    def _schedule_next_frame(self):
        if not self.playing or self.paused:
            return
        next_idx = (self.current_frame_idx + 1) % len(self.frames)
        if self.frames[next_idx] is None and not self.all_frames_loaded:
            self.after_id_frame = self.root.after(100, self._schedule_next_frame)
            return
        frame = self.frames[self.current_frame_idx]
        if frame is None:
            frame = self.frames[0]
        actual_delay = max(1, int(frame.duration / self.speed))
        self.after_id_frame = self.root.after(actual_delay, self._next_frame)

    def _next_frame(self):
        if not self.playing or self.paused:
            return
        self.completed_duration += self.frames[self.current_frame_idx].duration
        self.current_frame_idx += 1
        if self.current_frame_idx >= len(self.frames):
            self._on_file_end()
            return
        self.frame_start_time = time.time()
        self._show_frame(self.current_frame_idx)
        self._schedule_next_frame()

    def _on_file_end(self):
        self.total_elapsed_ms += self.total_duration
        self.completed_duration = 0
        self.current_frame_idx = 0

        if self.repeat_mode.get() == "frames":
            if self.target_repeat > 1:
                self.current_repeat += 1
                if self.current_repeat < self.target_repeat:
                    self.status_var.set(f"重复播放中... ({self.current_repeat+1}/{self.target_repeat})")
                    self._play_current_file(from_beginning=True)
                    return
                else:
                    self.current_repeat = 0
        else:
            target_ms = self.min_duration_seconds.get() * 1000
            if self.total_elapsed_ms < target_ms:
                self.current_repeat += 1
                self.status_var.set(f"重复播放中... (累计 {self.total_elapsed_ms/1000:.1f}s / 目标 {target_ms/1000:.1f}s)")
                self._play_current_file(from_beginning=True)
                return

        self.current_repeat = 0
        self.total_elapsed_ms = 0
        mode = self.play_mode.get()
        if mode == "single_once":
            self._pause(keep_state=True)
            self.status_var.set("单曲播放完毕")
            return
        elif mode == "single_loop":
            self.select_file(self.current_file_index, auto_play=True)
            return
        elif mode == "sequential":
            next_idx = self.current_file_index + 1
            if next_idx < len(self.files):
                self.select_file(next_idx, auto_play=True)
            else:
                self._stop_playback()
                self.status_var.set("列表播放完毕")
            return
        elif mode == "loop_all":
            next_idx = self.current_file_index + 1
            if next_idx >= len(self.files):
                next_idx = 0
            self.select_file(next_idx, auto_play=True)
            return
        else:
            self._stop_playback()

    # ---------- 控制操作 ----------
    def toggle_play_pause(self):
        if not self.frames or not self.frames_ready:
            return
        if not self.playing:
            if self.current_file_index < 0:
                self.select_file(0)
            self._play_current_file(from_beginning=(self.current_frame_idx == 0 and self.completed_duration == 0))
        elif self.paused:
            self.paused = False
            self.playing = True
            self.frame_start_time = time.time()
            self._show_frame(self.current_frame_idx)
            self._schedule_next_frame()
            if self.after_id_progress:
                self.root.after_cancel(self.after_id_progress)
            self._progress_loop()
            self.play_pause_btn.config(text="⏸ 暂停")
            self.status_var.set("播放中...")
        else:
            self._pause(keep_state=False)

    def _pause(self, keep_state=False):
        if not keep_state:
            if self.playing and not self.paused:
                elapsed = (time.time() - self.frame_start_time) * self.speed * 1000
                self.completed_duration += elapsed
                self.paused = True
        if self.after_id_frame:
            self.root.after_cancel(self.after_id_frame)
            self.after_id_frame = None
        if self.after_id_progress:
            self.root.after_cancel(self.after_id_progress)
            self.after_id_progress = None
        if not keep_state:
            self.play_pause_btn.config(text="▶ 播放")
            self.status_var.set("已暂停")
        self._update_seekbar(self.completed_duration)

    def stop(self):
        self._stop_playback()
        if self.current_file_index >= 0:
            self.select_file(self.current_file_index)
        self.status_var.set("已停止")

    def _stop_playback(self, keep_selection=True):
        self.playing = False
        self.paused = False
        self.seek_dragging = False
        self.pending_play = False
        if self.after_id_frame:
            self.root.after_cancel(self.after_id_frame)
            self.after_id_frame = None
        if self.after_id_progress:
            self.root.after_cancel(self.after_id_progress)
            self.after_id_progress = None
        self.play_pause_btn.config(text="▶ 播放")
        if not keep_selection:
            self.current_file_index = -1
            self.frames = []
            self.cached_photos.clear()
            self.preloaded.clear()
        else:
            if self.frames:
                self.current_frame_idx = 0
                self.completed_duration = 0
                self._show_frame(0)
        self._update_total_progress()
        self._update_seekbar(0)

    def prev_file(self):
        if not self.files:
            return
        was_playing = self.playing and not self.paused
        new_idx = self.current_file_index - 1
        if new_idx < 0:
            new_idx = len(self.files) - 1
        self.select_file(new_idx, auto_play=was_playing)

    def next_file(self):
        if not self.files:
            return
        was_playing = self.playing and not self.paused
        new_idx = self.current_file_index + 1
        if new_idx >= len(self.files):
            new_idx = 0
        self.select_file(new_idx, auto_play=was_playing)

    def on_mode_change(self, value):
        self.mode_label.config(text=self.mode_text.get(value, ""))
        self.save_config()

    def on_speed_change(self, event=None):
        new_speed = self.speed_var.get()
        if self.playing and not self.paused:
            elapsed = (time.time() - self.frame_start_time) * self.speed * 1000
            self.completed_duration += elapsed
            self.speed = new_speed
            if self.after_id_frame:
                self.root.after_cancel(self.after_id_frame)
            frame = self.frames[self.current_frame_idx]
            if frame is None:
                return
            sum_before = sum(f.duration for f in self.frames[:self.current_frame_idx] if f)
            elapsed_in_frame = self.completed_duration - sum_before
            self.completed_duration = sum_before
            remaining_original = max(0, frame.duration - elapsed_in_frame)
            remaining_delay = max(1, int(remaining_original / self.speed))
            self.frame_start_time = time.time() - (elapsed_in_frame / self.speed / 1000)
            self.after_id_frame = self.root.after(remaining_delay, self._next_frame)
        else:
            self.speed = new_speed

    def on_image_duration_change(self, *args):
        self.save_config()
        # 如果当前文件是静态图片且已加载，更新其duration
        if not self.frames or len(self.frames) != 1:
            return
        # 判断当前文件是否为静态图片（通过扩展名）
        path = self.files[self.current_file_index] if self.current_file_index >= 0 else None
        if path and not path.lower().endswith('.gif'):
            new_duration = int(self.image_duration_seconds.get() * 1000)
            if new_duration < 20:
                new_duration = 100
            # 更新帧duration
            self.frames[0] = GifFrame(self.frames[0].image, new_duration)
            self.total_duration = new_duration

            # 如果正在播放，调整定时器
            if self.playing and not self.paused and self.current_frame_idx == 0:
                elapsed = (time.time() - self.frame_start_time) * self.speed * 1000
                remaining = max(0, new_duration - elapsed)
                if self.after_id_frame:
                    self.root.after_cancel(self.after_id_frame)
                    self.after_id_frame = None
                self.after_id_frame = self.root.after(int(remaining / self.speed), self._next_frame)
                self._update_seekbar(elapsed)

    def on_closing(self):
        self.save_config()
        self._stop_playback(keep_selection=False)
        self.root.destroy()

    def bind_shortcuts(self):
        self.root.bind("<space>", lambda e: self.toggle_play_pause())
        self.root.bind("<Left>", lambda e: self.prev_file())
        self.root.bind("<Right>", lambda e: self.next_file())
        self.root.bind("<Up>", lambda e: self.prev_file())
        self.root.bind("<Down>", lambda e: self.next_file())
        self.root.bind("<Control-f>", lambda e: self.toggle_favorite())
        self.root.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.root.bind("<Escape>", self.exit_fullscreen_event)
        self.canvas.bind("<Configure>", self.on_canvas_resize)


if __name__ == "__main__":
    root = tk.Tk()
    app = GifPlayer(root)
    root.mainloop()