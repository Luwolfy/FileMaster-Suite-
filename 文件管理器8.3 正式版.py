#!/usr/bin/env python3
"""
FileManager Pro - 全能文件管理工具 (Windows桌面版) 【美化版】
支持：筛选、提取、分类、批量重命名、智能分析、文件清理
优化点：界面自适应、统一配色、样式美化、布局增强
"""

import os
import shutil
import json
import re
import threading
import time
import hashlib
import mimetypes
import zipfile
import tarfile
from datetime import datetime, timedelta
from collections import defaultdict
import fnmatch
import tkinter as tk
from tkinter import (
    ttk, filedialog, messagebox, scrolledtext, simpledialog
)
import tkinter.font as tkfont
from tkinterdnd2 import DND_FILES, TkinterDnD
import platform
from pathlib import Path
import math


# ===================== 工具类 =====================
class ToolTip:
    """增强版工具提示类"""
    def __init__(self, widget, text, delay=0.2):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip = None
        self.id = None
        self.widget.bind("<Enter>", self.schedule_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)
        self.widget.bind("<ButtonPress>", self.hide_tooltip)

    def schedule_tooltip(self, event=None):
        self.id = self.widget.after(int(self.delay * 1000), self.show_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip:
            return
        try:
            screen_w = self.widget.winfo_screenwidth()
            screen_h = self.widget.winfo_screenheight()
            x = self.widget.winfo_pointerx() + 10
            y = self.widget.winfo_pointery() + 10

            try:
                dpi = self.widget.winfo_toplevel().winfo_fpixels('1i')
            except Exception:
                dpi = 96.0
            scale = float(dpi) / 96.0
            scale = min(max(0.8, scale), 2.0)

            wrap_len = int(min(400, screen_w * 0.3))
            base_size = max(8, int(9 * scale))
            try:
                font_family = "Microsoft YaHei" if platform.system() == 'Windows' else "Arial"
            except Exception:
                font_family = "Arial"
            label_font = tkfont.Font(family=font_family, size=base_size)

            est_w = wrap_len + 40
            est_h = int(base_size * 4) + 20
            if x + est_w > screen_w:
                x = max(10, screen_w - est_w - 10)
            if y + est_h > screen_h:
                y = max(10, screen_h - est_h - 10)

            self.tooltip = tk.Toplevel(self.widget)
            self.tooltip.wm_overrideredirect(True)
            self.tooltip.wm_geometry(f"+{x}+{y}")
            try:
                self.tooltip.attributes('-topmost', True)
            except Exception:
                pass
            self.tooltip.configure(bg="#ffffe0")

            label = ttk.Label(
                self.tooltip,
                text=self.text,
                background="#ffffe0",
                relief=tk.SOLID,
                borderwidth=1,
                font=label_font,
                wraplength=wrap_len,
                justify=tk.LEFT
            )
            label.pack(ipadx=8, ipady=4)
        except Exception:
            try:
                x = self.widget.winfo_pointerx() + 10
                y = self.widget.winfo_pointery() + 10
                self.tooltip = tk.Toplevel(self.widget)
                self.tooltip.wm_overrideredirect(True)
                self.tooltip.wm_geometry(f"+{x}+{y}")
                self.tooltip.attributes('-topmost', True)
                label = ttk.Label(self.tooltip, text=self.text, background="#ffffe0", relief=tk.SOLID, borderwidth=1)
                label.pack(ipadx=6, ipady=3)
            except Exception:
                pass

    def hide_tooltip(self, event=None):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


# ===================== 核心功能类 (优化版) =====================
class FileAnalyzer:
    def __init__(self):
        self.stats = {
            'by_extension': defaultdict(int),
            'by_size': {'tiny(<0.1M)': 0, 'small(0.1-1M)': 0, 'medium(1-100M)': 0, 'large(100M-1G)': 0, 'huge(>1G)': 0},
            'by_date': defaultdict(int),
            'duplicates': [],
            'name_patterns': defaultdict(int),
            'total_files': 0,
            'total_size': 0
        }

    def analyze_names(self, files):
        patterns = {
            '日期格式(2024-01-01/20240101)': r'\d{4}[-_]\d{2}[-_]\d{2}|\d{8}',
            '版本号(v1.0/r5)': r'v?\d+\.\d+(\.\d+)?|r\d+',
            '剧集(S01E01/1x01)': r'[Ss]\d{1,2}[Ee]\d{1,2}|\d{1,2}x\d{2}',
            '分辨率(1080p/4K)': r'\d{3,4}[pP]|[24]K|1080[iIpP]|720[iIpP]',
            '年份(2024)': r'\(?\d{4}\)?',
            '哈希值(8-32位)': r'[a-f0-9]{8,32}',
            '画质标识(bluray/webrip)': r'bluray|webrip|web-dl|hdtv|hdr|xvid|x264|x265|hevc|aac|dts',
            '分组标识(-GROUP)': r'-[A-Za-z0-9]+$'
        }
        for f in files:
            name = f['name']
            for ptype, pattern in patterns.items():
                if re.search(pattern, name, re.I):
                    self.stats['name_patterns'][ptype] += 1
        return dict(self.stats['name_patterns'])

    def update_total_stats(self, files):
        self.stats['total_files'] = len(files)
        self.stats['total_size'] = sum(f['size'] for f in files)


class BatchRenamer:
    def __init__(self):
        self.operations = []

    def add_operation(self, op_type, **kwargs):
        self.operations.append({'type': op_type, 'params': kwargs})

    def preview(self, filename, index=0):
        result = filename
        for op in self.operations:
            if op['type'] == 'numbering':
                op['params']['index'] = index
            result = self._apply_op(result, op)
        return result

    def _apply_op(self, name, operation):
        op_type = operation['type']
        params = operation['params']
        base, ext = os.path.splitext(name)
        try:
            if op_type == 'replace':
                return name.replace(params['old'], params['new'])
            elif op_type == 'regex':
                return re.sub(params['pattern'], params['replacement'], name)
            elif op_type == 'case':
                case = params['case']
                if case == 'lower':
                    return name.lower()
                elif case == 'upper':
                    return name.upper()
                elif case == 'title':
                    return name.title()
                elif case == 'capitalize':
                    return base.capitalize() + ext
            elif op_type == 'add_prefix':
                return params['prefix'] + name
            elif op_type == 'add_suffix':
                return base + params['suffix'] + ext
            elif op_type == 'remove':
                start = params.get('start', 0)
                end = params.get('end', None)
                if end:
                    return base[:start] + base[end:] + ext
                return base[start:] + ext
            elif op_type == 'numbering':
                idx = params.get('index', 0)
                width = params.get('width', 3)
                num = str(idx).zfill(width)
                pos = params.get('position', 'end')
                if pos == 'start':
                    return num + '_' + name
                else:
                    return base + '_' + num + ext
            elif op_type == 'clean':
                cleaned = re.sub(r'[_\-\s]+', ' ', name)
                cleaned = re.sub(r'[^\w\s\.\-]', '', cleaned)
                return cleaned.strip()
            elif op_type == 'date':
                fmt = params.get('format', '%Y%m%d')
                if 'custom_date' in params and params['custom_date']:
                    date_str = params['custom_date']
                else:
                    date_str = datetime.now().strftime(fmt)
                pos = params.get('position', 'prefix')
                if pos == 'prefix':
                    return date_str + '_' + name
                else:
                    return base + '_' + date_str + ext
            elif op_type == 'format':
                fmt_str = params.get('template', '')
                idx = params.get('index', 0)
                base_name = base

                def extract_token(match):
                    token = match.group(1)
                    if ':' in token:
                        key, arg = token.split(':', 1)
                    else:
                        key, arg = token, None
                    try:
                        if key == 'name':
                            return base_name
                        if key == 'ext':
                            return ext
                        if key == 'index':
                            if arg and arg.isdigit():
                                return str(idx).zfill(int(arg))
                            return str(idx)
                        if key == 'date':
                            fmtdate = arg or '%Y%m%d'
                            return datetime.now().strftime(fmtdate)
                        if key == 'left' and arg:
                            n = int(arg)
                            return base_name[:n]
                        if key == 'right' and arg:
                            n = int(arg)
                            return base_name[-n:] if n > 0 else ''
                        if key == 'mid' and arg:
                            parts = [p.strip() for p in arg.split(',') if p.strip()]
                            if len(parts) >= 2:
                                start = int(parts[0]) - 1 if int(parts[0]) > 0 else 0
                                length = int(parts[1])
                                if length <= 0:
                                    return base_name[start:]
                                return base_name[start:start+length]
                    except Exception:
                        return ''
                    return ''

                if not fmt_str:
                    return name
                new_base = re.sub(r"\{([^}]+)\}", extract_token, fmt_str)
                if '{ext}' not in fmt_str and not new_base.endswith(ext):
                    return new_base + ext
                return new_base
            elif op_type == 'trim':
                return base.strip() + ext
        except Exception as e:
            print(f"重命名操作失败: {e}")
            return name
        return name


class FileManager:
    def __init__(self):
        self.white_rules = []
        self.black_rules = []
        self.max_depth = 0
        self.scanning = False
        self.scan_progress = 0
        self.current_task = None
        self.analyzer = FileAnalyzer()
        self.renamer = BatchRenamer()
        self.cache = {}
        self.scan_cancel = False

    def add_rule(self, rule_type, pattern, is_black=False, use_regex=False):
        rule = {
            'id': hashlib.md5(f"{time.time()}_{pattern}".encode()).hexdigest()[:8],
            'type': rule_type,
            'pattern': pattern,
            'regex': use_regex,
            'black': is_black,
            'created': time.time(),
            'desc': self._get_rule_desc(rule_type, pattern, is_black, use_regex)
        }
        if is_black:
            self.black_rules.append(rule)
        else:
            self.white_rules.append(rule)
        return rule

    def _get_rule_desc(self, rule_type, pattern, is_black, use_regex):
        rule_type_cn = {
            'name': '文件名',
            'ext': '扩展名',
            'path': '路径',
            'size': '文件大小',
            'date': '修改日期'
        }
        black_cn = '黑名单(排除)' if is_black else '白名单(保留)'
        regex_cn = '正则匹配' if use_regex else '包含匹配'
        return f"{black_cn} | {rule_type_cn.get(rule_type, rule_type)} | {regex_cn} | {pattern}"

    def remove_rule(self, rule_id):
        self.white_rules = [r for r in self.white_rules if r['id'] != rule_id]
        self.black_rules = [r for r in self.black_rules if r['id'] != rule_id]

    def clear_rules(self):
        self.white_rules = []
        self.black_rules = []

    def cancel_scan(self):
        self.scan_cancel = True
        self.scanning = False

    def scan(self, source_path, use_cache=True, callback=None):
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"目录不存在: {source_path}")
        cache_key = f"{source_path}_{self.max_depth}"
        if use_cache and cache_key in self.cache:
            return self.cache[cache_key]
        self.scanning = True
        self.scan_progress = 0
        self.scan_cancel = False
        files = []
        dirs = []
        self.analyzer = FileAnalyzer()
        total_files = 0
        try:
            for root, dirnames, filenames in os.walk(source_path):
                total_files += len(filenames)
                if self.scan_cancel:
                    break
                if total_files > 100000:
                    total_files = -1
                    break
        except Exception:
            total_files = -1
        processed = 0
        last_update = time.time()
        for root, dirnames, filenames in os.walk(source_path):
            if self.scan_cancel or not self.scanning:
                break
            rel_root = os.path.relpath(root, source_path)
            depth = 0 if rel_root == '.' else len(rel_root.split(os.sep))
            if self.max_depth > 0 and depth >= self.max_depth:
                del dirnames[:]
                continue
            for filename in filenames:
                if self.scan_cancel:
                    break
                filepath = os.path.join(root, filename)
                try:
                    stat = os.stat(filepath)
                    ext = os.path.splitext(filename)[1].lower()
                    file_info = {
                        'path': filepath,
                        'name': filename,
                        'rel_path': os.path.relpath(filepath, source_path),
                        'ext': ext,
                        'size': stat.st_size,
                        'mtime': stat.st_mtime,
                        'depth': depth + 1,
                        'mime': mimetypes.guess_type(filename)[0] or 'unknown',
                        'hash': None
                    }
                    files.append(file_info)
                    self.analyzer.stats['by_extension'][ext] += 1
                    size_mb = stat.st_size / (1024*1024)
                    if size_mb < 0.1:
                        self.analyzer.stats['by_size']['tiny(<0.1M)'] += 1
                    elif size_mb < 1:
                        self.analyzer.stats['by_size']['small(0.1-1M)'] += 1
                    elif size_mb < 100:
                        self.analyzer.stats['by_size']['medium(1-100M)'] += 1
                    elif size_mb < 1024:
                        self.analyzer.stats['by_size']['large(100M-1G)'] += 1
                    else:
                        self.analyzer.stats['by_size']['huge(>1G)'] += 1
                    date_key = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m')
                    self.analyzer.stats['by_date'][date_key] += 1
                except (OSError, PermissionError):
                    continue
                processed += 1
                now = time.time()
                if now - last_update > 0.2 and callback and total_files > 0:
                    self.scan_progress = min(100, int(processed / max(total_files, 1) * 100))
                    callback(self.scan_progress, len(files))
                    last_update = now
        self.analyzer.update_total_stats(files)
        result = {
            'files': files,
            'dirs': dirs,
            'total_size': sum(f['size'] for f in files),
            'stats': self.analyzer.stats
        }
        if not self.scan_cancel:
            self.cache[cache_key] = result
        self.scanning = False
        self.scan_progress = 100 if not self.scan_cancel else 0
        if callback:
            callback(self.scan_progress, len(files))
        return result

    def filter_files(self, files):
        result = []
        for f in files:
            if self.white_rules and not self._match_any_rule(f, self.white_rules):
                f['status'] = 'filtered'
                f['reason'] = '未匹配白名单规则'
                continue
            if self.black_rules and self._match_any_rule(f, self.black_rules):
                f['status'] = 'excluded'
                f['reason'] = '匹配黑名单规则'
                continue
            f['status'] = 'selected'
            f['reason'] = '通过筛选'
            result.append(f)
        return result

    def _match_any_rule(self, file_info, rules):
        for rule in rules:
            if self._match_rule(file_info, rule):
                return True
        return False

    def _match_rule(self, file_info, rule):
        rule_type = rule['type']
        pattern = rule['pattern']
        use_regex = rule['regex']
        try:
            if use_regex:
                flags = re.IGNORECASE
                if rule_type == 'ext':
                    return bool(re.search(pattern, file_info['ext'], flags))
                elif rule_type == 'name':
                    return bool(re.search(pattern, file_info['name'], flags))
                elif rule_type == 'path':
                    return bool(re.search(pattern, file_info['rel_path'], flags))
                elif rule_type == 'size':
                    return self._match_size(file_info['size'], pattern)
                elif rule_type == 'date':
                    return self._match_date(file_info['mtime'], pattern)
            else:
                pattern = pattern.lower()
                if rule_type == 'ext':
                    return pattern in file_info['ext']
                elif rule_type == 'name':
                    return pattern in file_info['name'].lower()
                elif rule_type == 'path':
                    return pattern in file_info['rel_path'].lower()
        except Exception as e:
            print(f"规则匹配失败: {e}")
        return False

    def _match_size(self, size_bytes, pattern):
        pattern = pattern.strip()
        units = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}

        def parse_size(s):
            s = s.strip().upper()
            for unit, mult in units.items():
                if unit in s:
                    num = re.findall(r'\d+\.?\d*', s)
                    if num:
                        return float(num[0]) * mult
            return float(s) if s.replace('.','').isdigit() else 0

        if pattern.startswith('>'):
            return size_bytes > parse_size(pattern[1:])
        elif pattern.startswith('<'):
            return size_bytes < parse_size(pattern[1:])
        elif '-' in pattern:
            parts = pattern.split('-')
            if len(parts) == 2:
                min_s = parse_size(parts[0])
                max_s = parse_size(parts[1])
                return min_s <= size_bytes <= max_s
        return False

    def _match_date(self, mtime, pattern):
        try:
            file_date = datetime.fromtimestamp(mtime)
            if pattern.startswith('>') and '-' in pattern[1:]:
                target_date = datetime.strptime(pattern[1:].strip(), '%Y-%m-%d')
                return file_date > target_date
            elif pattern.startswith('<') and '-' in pattern[1:]:
                target_date = datetime.strptime(pattern[1:].strip(), '%Y-%m-%d')
                return file_date < target_date
            rel_pattern = pattern[1:] if pattern.startswith(('>', '<')) else pattern
            if rel_pattern.endswith('d'):
                days = int(rel_pattern[:-1])
                target_date = datetime.now() - timedelta(days=days)
                if pattern.startswith('>'):
                    return file_date < target_date
                else:
                    return file_date > target_date
            elif rel_pattern.endswith('m'):
                months = int(rel_pattern[:-1])
                target_date = datetime.now() - timedelta(days=months*30)
                if pattern.startswith('>'):
                    return file_date < target_date
                else:
                    return file_date > target_date
            elif rel_pattern.endswith('y'):
                years = int(rel_pattern[:-1])
                target_date = datetime.now() - timedelta(days=years*365)
                if pattern.startswith('>'):
                    return file_date < target_date
                else:
                    return file_date > target_date
        except Exception as e:
            print(f"日期匹配失败: {e}")
        return False

    def find_duplicates(self, files, by='hash', progress_callback=None):
        if not files:
            return []
        duplicates = []
        total = len(files)
        processed = 0
        if by == 'hash':
            size_groups = defaultdict(list)
            for f in files:
                size_groups[f['size']].append(f)
                processed += 1
                if progress_callback and processed % 50 == 0:
                    progress_callback(int(processed/total*50))
            hash_processed = 0
            hash_total = sum(len(g) for g in size_groups.values() if len(g) > 1)
            for size, group in size_groups.items():
                if len(group) <= 1:
                    continue
                hashes = defaultdict(list)
                for f in group:
                    file_hash = self._get_file_hash(f['path'])
                    if file_hash:
                        hashes[file_hash].append(f)
                    hash_processed += 1
                    if progress_callback:
                        progress = 50 + int(hash_processed/hash_total*50)
                        progress_callback(min(100, progress))
                for h, items in hashes.items():
                    if len(items) > 1:
                        duplicates.append(items)
        elif by == 'name':
            name_groups = defaultdict(list)
            for f in files:
                name_groups[f['name'].lower()].append(f)
                processed += 1
                if progress_callback and processed % 50 == 0:
                    progress_callback(int(processed/total*100))
            duplicates = [g for g in name_groups.values() if len(g) > 1]
        return duplicates

    def _get_file_hash(self, filepath, limit=8192):
        try:
            if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                return None
            hasher = hashlib.md5()
            with open(filepath, 'rb') as f:
                chunk = f.read(limit)
                if chunk:
                    hasher.update(chunk)
                file_size = os.path.getsize(filepath)
                if file_size > limit * 2:
                    f.seek(max(-limit, -file_size), 2)
                    chunk = f.read(limit)
                    if chunk:
                        hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            print(f"计算哈希失败 {filepath}: {e}")
            return None

    def categorize(self, files):
        categories = {
            '图片': {'exts': ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tiff', '.ico'], 'files': []},
            '视频': {'exts': ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpeg', '.mpg'], 'files': []},
            '音频': {'exts': ['.mp3', '.flac', '.wav', '.aac', '.ogg', '.m4a', '.wma', '.ape'], 'files': []},
            '文档': {'exts': ['.pdf', '.doc', '.docx', '.txt', '.md', '.xls', '.xlsx', '.ppt', '.pptx', '.csv', '.rtf'], 'files': []},
            '压缩包': {'exts': ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.iso', '.cab'], 'files': []},
            '代码': {'exts': ['.py', '.js', '.html', '.css', '.java', '.cpp', '.c', '.h', '.go', '.rs', '.php', '.sh', '.bat'], 'files': []},
            '可执行文件': {'exts': ['.exe', '.msi', '.dmg', '.pkg', '.deb', '.rpm', '.sh', '.bin'], 'files': []},
            '临时文件': {'exts': ['.tmp', '.temp', '.bak', '.swp', '.log'], 'files': []}
        }
        for f in files:
            ext = f['ext'].lower()
            categorized = False
            for cat_name, cat_info in categories.items():
                if ext in cat_info['exts']:
                    cat_info['files'].append(f)
                    categorized = True
                    break
            if not categorized:
                if '其他文件' not in categories:
                    categories['其他文件'] = {'exts': [], 'files': []}
                categories['其他文件']['files'].append(f)
        return categories

    def batch_rename(self, files, operations, preview=False):
        if not files or not operations:
            return []
        self.renamer.operations = operations
        results = []
        for idx, f in enumerate(files):
            old_name = f['name']
            new_name = self.renamer.preview(old_name, idx + 1)
            if new_name == old_name:
                results.append({'old': old_name, 'new': new_name, 'path': f['path'], 'status': '未修改'})
                continue
            if not preview:
                try:
                    old_path = f['path']
                    new_path = os.path.join(os.path.dirname(old_path), new_name)
                    if os.path.exists(new_path):
                        results.append({'old': old_name, 'new': new_name, 'error': '目标文件已存在', 'status': '失败'})
                        continue
                    os.rename(old_path, new_path)
                    f['path'] = new_path
                    f['name'] = new_name
                    f['rel_path'] = os.path.relpath(new_path, os.path.dirname(os.path.dirname(old_path)))
                    results.append({'old': old_name, 'new': new_name, 'path': new_path, 'status': '成功'})
                except Exception as e:
                    results.append({'old': old_name, 'new': new_name, 'error': str(e), 'status': '失败'})
            else:
                results.append({'old': old_name, 'new': new_name, 'path': f['path'], 'status': '预览'})
        return results

    def extract(self, files, dest_path, keep_structure=False, conflict='rename', organize_by=None, callback=None):
        if not files:
            return {'success': [], 'skip': [], 'error': []}
        try:
            os.makedirs(dest_path, exist_ok=True)
        except Exception as e:
            return {'success': [], 'skip': [], 'error': [{'error': f'创建目录失败: {e}'}]}
        success, skip, error = [], [], []
        total = len(files)
        for idx, f in enumerate(files):
            source = f['path']
            if not os.path.exists(source):
                error.append({'path': source, 'error': '源文件不存在'})
                continue
            filename = f['name']
            try:
                if organize_by == '类型':
                    categories = self.categorize([f])
                    cat_name = next(iter(categories.keys()))
                    target_dir = os.path.join(dest_path, cat_name)
                elif organize_by == '日期':
                    date_str = datetime.fromtimestamp(f['mtime']).strftime('%Y-%m-%d')
                    target_dir = os.path.join(dest_path, date_str)
                elif organize_by == '大小':
                    size_mb = f['size'] / (1024*1024)
                    if size_mb < 10:
                        cat = '小文件(<10M)'
                    elif size_mb < 1000:
                        cat = '中文件(10M-1G)'
                    else:
                        cat = '大文件(>1G)'
                    target_dir = os.path.join(dest_path, cat)
                elif keep_structure:
                    rel_dir = os.path.dirname(f['rel_path'])
                    target_dir = os.path.join(dest_path, rel_dir)
                else:
                    target_dir = dest_path
                os.makedirs(target_dir, exist_ok=True)
                target = os.path.join(target_dir, filename)
                if os.path.exists(target):
                    if conflict == '跳过':
                        skip.append(f)
                        continue
                    elif conflict == '重命名':
                        base, ext = os.path.splitext(filename)
                        counter = 1
                        while os.path.exists(target):
                            new_name = f"{base}_{counter:03d}{ext}"
                            target = os.path.join(target_dir, new_name)
                            counter += 1
                            if counter > 999:
                                break
                    elif conflict == '覆盖':
                        if os.path.isfile(target):
                            os.remove(target)
                shutil.copy2(source, target)
                f['target'] = target
                success.append(f)
            except Exception as e:
                f['error'] = str(e)
                error.append(f)
            if callback and idx % 5 == 0:
                callback(int((idx + 1) / total * 100))
        return {'success': success, 'skip': skip, 'error': error}

    def delete_files(self, files, permanent=False):
        if not files:
            return {'success': [], 'error': []}
        trash_dir = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser("~")), 'Desktop', 'FileManager_Trash')
        success, error = [], []
        for f in files:
            try:
                source_path = f['path']
                if not os.path.exists(source_path):
                    error.append({'path': source_path, 'error': '文件不存在'})
                    continue
                if permanent:
                    if os.path.isfile(source_path):
                        os.remove(source_path)
                    success.append(f)
                else:
                    os.makedirs(trash_dir, exist_ok=True)
                    filename = f['name']
                    target_path = os.path.join(trash_dir, filename)
                    counter = 1
                    base, ext = os.path.splitext(filename)
                    while os.path.exists(target_path):
                        target_path = os.path.join(trash_dir, f"{base}_{counter:03d}{ext}")
                        counter += 1
                        if counter > 999:
                            break
                    shutil.move(source_path, target_path)
                    f['trash_path'] = target_path
                    success.append(f)
            except Exception as e:
                f['error'] = str(e)
                error.append(f)
        return {'success': success, 'error': error}

    def export_results(self, data, export_path, export_type='json'):
        try:
            if export_type == 'json':
                clean_data = {}
                if 'files' in data:
                    clean_data['files'] = [{k: v for k, v in f.items() if k != 'hash'} for f in data['files']]
                if 'stats' in data:
                    clean_data['stats'] = data['stats']
                clean_data['export_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with open(export_path, 'w', encoding='utf-8') as f:
                    json.dump(clean_data, f, ensure_ascii=False, indent=2)
            elif export_type == 'csv':
                import csv
                with open(export_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['文件名', '大小(字节)', '扩展名', '修改时间', '路径', '类型'])
                    for file in data.get('files', []):
                        mtime_str = datetime.fromtimestamp(file['mtime']).strftime('%Y-%m-%d %H:%M:%S')
                        writer.writerow([
                            file['name'],
                            file['size'],
                            file['ext'],
                            mtime_str,
                            file['path'],
                            file['mime']
                        ])
            return True
        except Exception as e:
            print(f"导出失败: {e}")
            return False


# ===================== GUI 界面类 (全面美化) =====================
class FileManagerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FileManager Pro - 全能文件管理工具 v5.2")

        # 主题调色板
        self.colors = {
            'primary': '#1976D2',
            'primary_dark': '#1565C0',
            'accent': '#FF6D00',
            'success': '#2E7D32',
            'warning': '#F57F17',
            'danger': '#C62828',
            'bg': '#FAFAFA',
            'surface': '#FFFFFF',
            'text': '#212121',
            'text_secondary': '#616161',
            'border': '#E0E0E0'
        }

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = int(screen_width * 0.9)
        window_height = int(screen_height * 0.85)
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")

        try:
            dpi = None
            if platform.system() == 'Windows':
                try:
                    import ctypes
                    try:
                        ctypes.windll.shcore.SetProcessDpiAwareness(1)
                    except Exception:
                        try:
                            ctypes.windll.user32.SetProcessDPIAware()
                        except Exception:
                            pass
                    try:
                        hwnd = self.root.winfo_id()
                        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                    except Exception:
                        dpi = None
                except Exception:
                    dpi = None
            if dpi is None:
                try:
                    dpi = self.root.winfo_fpixels('1i')
                except Exception:
                    dpi = 96.0
            raw_scale = float(dpi) / 96.0
            self.scale = min(max(0.8, raw_scale), 3.0)
            try:
                self.root.tk.call('tk', 'scaling', float(self.scale))
            except Exception:
                pass
            min_w = min(screen_width - 100, int(900 * self.scale))
            min_h = min(screen_height - 100, int(600 * self.scale))
            self.root.minsize(max(400, min_w), max(300, min_h))
            font_family = "Microsoft YaHei" if platform.system() == 'Windows' else "Arial"
            base_size = max(9, int(10 * self.scale))
            title_size = max(11, int(12 * self.scale))
            small_size = max(8, int(9 * self.scale))
            self.default_font = tkfont.Font(family=font_family, size=base_size)
            self.title_font = tkfont.Font(family=font_family, size=title_size, weight="bold")
            self.small_font = tkfont.Font(family=font_family, size=small_size)
        except Exception:
            self.scale = 1.0
            self.root.minsize(900, 600)
            font_family = "Microsoft YaHei" if platform.system() == 'Windows' else "Arial"
            self.default_font = tkfont.Font(family=font_family, size=10)
            self.title_font = tkfont.Font(family=font_family, size=11, weight="bold")
            self.small_font = tkfont.Font(family=font_family, size=9)

        self.manager = FileManager()
        self.current_files = []
        self.scanned_data = None
        self.selected_files = []
        self.is_working = False

        self.setup_style()
        self.create_widgets()
        self.log("程序已启动，就绪")

    def setup_style(self):
        self.style = ttk.Style()
        for theme in ('vista', 'xpnative', 'alt', 'clam'):
            try:
                self.style.theme_use(theme)
                break
            except tk.TclError:
                continue

        c = self.colors

        self.style.configure('.', font=self.default_font, background=c['bg'],
                             foreground=c['text'], fieldbackground='white')

        self.style.configure('TFrame', background=c['bg'])
        self.style.configure('TLabelframe', background=c['bg'], bordercolor=c['border'],
                             relief='groove', padding=12)
        self.style.configure('TLabelframe.Label', background=c['bg'], foreground=c['primary_dark'],
                             font=self.title_font)

        self.style.configure('TNotebook', background=c['bg'], tabmargins=[2, 5, 2, 0])
        self.style.configure('TNotebook.Tab', background=c['surface'], foreground=c['text'],
                             font=self.default_font, padding=[15, 6])
        self.style.map('TNotebook.Tab',
               background=[('selected', '#E3F2FD'), ('active', '#E3F2FD')],
               foreground=[('selected', c['text']), ('active', c['text'])])








        # 强调按钮（浅蓝）
        self.style.configure('Accent.TButton', foreground=c['text'],
                     background='#E3F2FD', relief='flat', borderwidth=0)
        self.style.map('Accent.TButton',
               background=[('active', '#E3F2FD'), ('disabled', c['bg'])],
               foreground=[('active', c['text']), ('disabled', '#9E9E9E')])

        # 警告按钮（浅红）
        self.style.configure('Warning.TButton', foreground=c['text'],
                            background='#FFCDD2', relief='flat', borderwidth=0)
        self.style.map('Warning.TButton',
                    background=[('active', '#FFCDD2'), ('disabled', c['bg'])],
                    foreground=[('active', c['text']), ('disabled', '#9E9E9E')])







        self.style.configure('Success.TButton', background=c['success'], foreground='white')
        self.style.map('Success.TButton', background=[('active', '#1B5E20')])

        self.style.configure('Treeview', background='white', fieldbackground='white',
                             foreground=c['text'], rowheight=int(30 * self.scale))
        self.style.configure('Treeview.Heading', background='#ECEFF1', foreground=c['text'],
                             font=self.title_font, relief='flat', padding=8)
        self.style.map('Treeview',
               background=[('selected', self.colors['primary'])],
               foreground=[('selected', 'white')])
        self.style.configure('TProgressbar', thickness=8, background=c['primary'],
                             troughcolor='#ECEFF1', borderwidth=0)

        self.style.configure('TEntry', padding=6, relief='solid', borderwidth=1)
        self.style.map('TEntry', bordercolor=[('focus', c['primary'])])

        self.style.configure('TScrollbar', background=c['bg'], bordercolor=c['border'],
                             arrowcolor=c['text_secondary'])
        








    def create_widgets(self):
        # 使用 PanedWindow 允许拖拽分隔条
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ========== 左侧面板（可滚动） ==========
        left_panel = ttk.Frame(main_pane)
        main_pane.add(left_panel, weight=1)          # 初始占比

        canvas = tk.Canvas(left_panel, highlightthickness=0, bg=self.colors['bg'])
        scrollbar = ttk.Scrollbar(left_panel, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # 鼠标滚轮仅在 Canvas 上生效
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.build_left_panel(scrollable_frame)

        # ========== 右侧主内容 ==========
        right_panel = ttk.Frame(main_pane)
        main_pane.add(right_panel, weight=3)          # 右侧更大
        self.build_right_panel(right_panel)

        # 底部状态栏
        self.status_bar = ttk.Label(self.root, text="✅ 就绪", relief=tk.SUNKEN, padding=8)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)









    def build_left_panel(self, parent):
        # 标题
        title_frame = ttk.Frame(parent)
        title_frame.pack(fill=tk.X, padx=10, pady=10)
        title_label = ttk.Label(title_frame, text="📂 FileManager Pro", font=tkfont.Font(family=self.default_font['family'], size=14, weight="bold"))
        title_label.pack(side=tk.LEFT)
        help_btn = ttk.Button(title_frame, text="❓ 帮助", command=self.show_help, width=8)
        help_btn.pack(side=tk.RIGHT)
        ToolTip(help_btn, "查看使用帮助和规则说明")

        # 扫描区域
        self.scan_frame = ttk.LabelFrame(parent, text="📁 目录扫描")
        self.scan_frame.pack(fill=tk.X, padx=10, pady=8)
        dir_row = ttk.Frame(self.scan_frame)
        dir_row.pack(fill=tk.X, pady=5)
        select_dir_btn = ttk.Button(dir_row, text="选择目录", command=self.select_scan_dir, width=10)
        select_dir_btn.pack(side=tk.LEFT)
        ToolTip(select_dir_btn, "选择要扫描的文件夹路径")
        self.path_var = tk.StringVar(value="未选择目录")
        path_label = ttk.Label(dir_row, textvariable=self.path_var, wraplength=220, justify=tk.LEFT)
        path_label.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        config_row = ttk.Frame(self.scan_frame)
        config_row.pack(fill=tk.X, pady=5)
        ttk.Label(config_row, text="扫描深度：", width=8).pack(side=tk.LEFT)
        self.depth_var = tk.IntVar(value=0)
        depth_spin = ttk.Spinbox(config_row, from_=0, to=20, textvariable=self.depth_var, width=6)
        depth_spin.pack(side=tk.LEFT, padx=2)
        ToolTip(depth_spin, "0=无限制深度\n1=仅当前目录\n2=包含子目录一级")
        self.use_cache_var = tk.BooleanVar(value=True)
        cache_check = ttk.Checkbutton(config_row, text="使用缓存", variable=self.use_cache_var)
        cache_check.pack(side=tk.LEFT, padx=8)
        ToolTip(cache_check, "使用缓存可加快重复扫描速度")

        btn_row = ttk.Frame(self.scan_frame)
        btn_row.pack(fill=tk.X, pady=8)
        self.scan_btn = ttk.Button(btn_row, text="▶ 开始扫描", command=self.start_scan, style="Accent.TButton")
        self.scan_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.cancel_scan_btn = ttk.Button(btn_row, text="⏹ 取消", command=self.cancel_scan, state=tk.DISABLED)
        self.cancel_scan_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ToolTip(self.scan_btn, "开始扫描选定目录下的所有文件")
        ToolTip(self.cancel_scan_btn, "取消当前扫描操作")

        progress_frame = ttk.Frame(self.scan_frame)
        progress_frame.pack(fill=tk.X, pady=5)
        self.scan_progress = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, length=240, mode='determinate')
        self.scan_progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_label = ttk.Label(progress_frame, text="0%", width=4)
        self.progress_label.pack(side=tk.RIGHT)

        # 过滤规则区域（保持原样）
        self.rules_frame = ttk.LabelFrame(parent, text="⚡ 过滤规则")
        self.rules_frame.pack(fill=tk.X, padx=10, pady=8)

        rule_help_btn = ttk.Button(self.rules_frame, text="规则说明", command=self.show_rule_help, width=8)
        rule_help_btn.pack(anchor=tk.W, pady=3)

        rule_input_frame = ttk.Frame(self.rules_frame)
        rule_input_frame.pack(fill=tk.X, pady=5)
        self.rule_type = ttk.Combobox(rule_input_frame, values=['name', 'ext', 'path', 'size', 'date'], width=8, state="readonly")
        self.rule_type.set('name')
        self.rule_type.pack(side=tk.LEFT, padx=2)
        ToolTip(self.rule_type, "选择规则匹配的维度\nname=文件名\next=扩展名\npath=路径\nsize=文件大小\ndate=修改日期")
        self.rule_pattern = ttk.Entry(rule_input_frame, width=15)
        self.rule_pattern.pack(side=tk.LEFT, padx=2)
        ToolTip(self.rule_pattern, "输入匹配模式（点击规则说明查看示例）")

        advanced_frame = ttk.Frame(rule_input_frame)
        advanced_frame.pack(side=tk.LEFT, padx=2)
        self.regex_var = tk.BooleanVar()
        regex_check = ttk.Checkbutton(advanced_frame, text="正则", variable=self.regex_var)
        regex_check.pack(side=tk.LEFT)
        ToolTip(regex_check, "使用正则表达式匹配模式")
        self.black_var = tk.BooleanVar()
        black_check = ttk.Checkbutton(advanced_frame, text="黑名单", variable=self.black_var)
        black_check.pack(side=tk.LEFT)
        ToolTip(black_check, "匹配此规则的文件将被排除")

        rule_btn_frame = ttk.Frame(self.rules_frame)
        rule_btn_frame.pack(fill=tk.X, pady=5)
        add_rule_btn = ttk.Button(rule_btn_frame, text="添加", command=self.add_rule, width=8)
        add_rule_btn.pack(side=tk.LEFT, padx=2)
        ToolTip(add_rule_btn, "添加新的过滤规则")
        remove_rule_btn = ttk.Button(rule_btn_frame, text="删除选中", command=self.remove_selected_rule, width=8)
        remove_rule_btn.pack(side=tk.LEFT, padx=2)
        ToolTip(remove_rule_btn, "删除选中的过滤规则")
        clear_rule_btn = ttk.Button(rule_btn_frame, text="清空", command=self.clear_rules, width=8)
        clear_rule_btn.pack(side=tk.LEFT, padx=2)
        ToolTip(clear_rule_btn, "清空所有过滤规则")

        rules_list_frame = ttk.Frame(self.rules_frame)
        rules_list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.rules_listbox = tk.Listbox(rules_list_frame, height=6, font=self.small_font,
                                       selectbackground=self.colors['primary'], selectforeground="white",
                                       bd=1, relief=tk.SOLID)
        rules_scroll = ttk.Scrollbar(rules_list_frame, orient=tk.VERTICAL, command=self.rules_listbox.yview)
        self.rules_listbox.configure(yscrollcommand=rules_scroll.set)
        self.rules_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rules_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        ToolTip(self.rules_listbox, "选中规则可删除\n支持多选（Ctrl/Shift）")

        # 文件操作区域
        self.functions_frame = ttk.LabelFrame(parent, text="🔧 文件操作")
        self.functions_frame.pack(fill=tk.X, padx=10, pady=8)

        basic_ops_frame = ttk.Frame(self.functions_frame)
        basic_ops_frame.pack(fill=tk.X, pady=3)
        fun_btns_basic = [
            ("📊 分类文件", self.categorize_files, "按文件类型自动分类并显示"),
            ("🔍 查找重复", self.find_duplicates, "查找重复文件（按名称/哈希）"),
            ("✏️ 批量重命名", self.batch_rename_dialog, "批量修改文件名（支持预览）"),
            ("📤 提取/复制", self.extract_files, "提取文件到指定目录（可分类）"),
        ]
        for text, cmd, tip in fun_btns_basic:
            btn = ttk.Button(basic_ops_frame, text=text, command=cmd)
            btn.pack(fill=tk.X, pady=2)
            ToolTip(btn, tip)

        advanced_ops_frame = ttk.Frame(self.functions_frame)
        advanced_ops_frame.pack(fill=tk.X, pady=8)
        fun_btns_advanced = [
            ("🗑️ 删除文件", self.delete_files, "删除选中文件（默认移至回收站）", "Warning.TButton"),
            ("📈 分析文件", self.analyze_files, "分析文件统计信息并生成报告"),
            ("📤 导出结果", self.export_results, "导出扫描/分析结果为JSON/CSV"),
        ]
        for item in fun_btns_advanced:
            text, cmd, tip = item[:3]
            style = item[3] if len(item) > 3 else "TButton"
            btn = ttk.Button(advanced_ops_frame, text=text, command=cmd, style=style)
            btn.pack(fill=tk.X, pady=2)
            ToolTip(btn, tip)

    def build_right_panel(self, right_panel):
        toolbar_frame = ttk.Frame(right_panel)
        toolbar_frame.pack(fill=tk.X, padx=5, pady=5)

        filter_btn = ttk.Button(toolbar_frame, text="🔍 应用过滤规则", command=self.apply_filter)
        filter_btn.pack(side=tk.LEFT, padx=2)
        ToolTip(filter_btn, "应用当前过滤规则筛选文件列表")
        refresh_btn = ttk.Button(toolbar_frame, text="🔄 刷新列表", command=self.refresh_file_list)
        refresh_btn.pack(side=tk.LEFT, padx=2)
        ToolTip(refresh_btn, "刷新当前文件列表")

        self.select_all_var = tk.BooleanVar()
        select_all_check = ttk.Checkbutton(toolbar_frame, text="全选", variable=self.select_all_var, command=self.toggle_select_all)
        select_all_check.pack(side=tk.LEFT, padx=10)
        ToolTip(select_all_check, "全选/取消全选文件列表中的文件")

        self.selected_count_var = tk.StringVar(value="选中: 0 个文件")
        count_label = ttk.Label(toolbar_frame, textvariable=self.selected_count_var)
        count_label.pack(side=tk.RIGHT, padx=5)
        self.total_count_var = tk.StringVar(value="总文件: 0 个")
        self.passed_count_var = tk.StringVar(value="将通过: 0 个")
        self.excluded_count_var = tk.StringVar(value="已排除: 0 个")
        excl_label = ttk.Label(toolbar_frame, textvariable=self.excluded_count_var)
        excl_label.pack(side=tk.RIGHT, padx=8)
        passed_label = ttk.Label(toolbar_frame, textvariable=self.passed_count_var)
        passed_label.pack(side=tk.RIGHT, padx=8)
        total_label = ttk.Label(toolbar_frame, textvariable=self.total_count_var)
        total_label.pack(side=tk.RIGHT, padx=8)

        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.files_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.files_tab, text="📋 文件列表")
        file_tree_frame = ttk.Frame(self.files_tab)
        file_tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.file_tree = ttk.Treeview(file_tree_frame, columns=('name', 'size', 'type', 'mtime', 'path', 'status'),
                                      show='headings', selectmode='extended')
        columns_config = {
            'name': ('文件名', 200),
            'size': ('大小', 100),
            'type': ('类型', 90),
            'mtime': ('修改时间', 180),
            'path': ('路径', 300),
            'status': ('状态', 100)
        }
        self._column_base_widths = {}
        for col, (text, width) in columns_config.items():
            self._column_base_widths[col] = width
            self.file_tree.heading(col, text=text, command=lambda c=col: self.sort_tree(c))
            scaled_width = int(max(60, width * self.scale))
            min_w = int(max(60, 80 * self.scale))
            self.file_tree.column(col, width=scaled_width, minwidth=min_w, stretch=tk.YES)

        tree_scroll_y = ttk.Scrollbar(file_tree_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        tree_scroll_x = ttk.Scrollbar(file_tree_frame, orient=tk.HORIZONTAL, command=self.file_tree.xview)
        self.file_tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.file_tree.bind('<<TreeviewSelect>>', self.on_file_select)

        # 交替行颜色
        self.file_tree.tag_configure('oddrow', background="#E8E8E8")
        self.file_tree.tag_configure('evenrow', background='white')
# 不要额外定义 'selected' tag

        self.stats_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.stats_tab, text="📊 统计信息")
        self.stats_text = scrolledtext.ScrolledText(self.stats_tab, wrap=tk.WORD, font=self.default_font,
                                                    bg=self.colors['surface'], relief=tk.FLAT, bd=1)
        self.stats_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.stats_text.config(state=tk.DISABLED)

        self.log_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.log_tab, text="📄 操作日志")
        self.log_text = scrolledtext.ScrolledText(self.log_tab, wrap=tk.WORD, font=self.small_font,
                                                  bg=self.colors['surface'], relief=tk.FLAT, bd=1)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)

    # ---------- 以下所有方法保持原功能不变，仅微调样式相关代码 ----------
    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.status_bar.config(text=f"✅ {message[:50]}...")

    def update_status(self, text):
        self.status_bar.config(text=text)
        self.root.update_idletasks()

    def update_counts(self, total=None, passed=None):
        try:
            if total is None:
                if self.scanned_data and 'files' in self.scanned_data:
                    total = len(self.scanned_data['files'])
                else:
                    total = len(getattr(self, 'current_files', []))
            if passed is None:
                cur = getattr(self, 'current_files', [])
                sel = sum(1 for f in cur if f.get('status') == 'selected')
                passed = sel if sel > 0 else len(cur)
            excluded = max(0, total - passed)
            self.total_count_var.set(f"总文件: {total} 个")
            self.passed_count_var.set(f"将通过: {passed} 个")
            self.excluded_count_var.set(f"已排除: {excluded} 个")
        except Exception:
            pass

    def show_help(self):
        help_text = """
📖 FileManager Pro 使用帮助
一、规则类型（rule_type）
   - name  : 文件名（不含路径）
   - ext   : 扩展名（如 .txt, .py）
   - path  : 相对路径（相对于扫描根目录）
   - size  : 文件大小（支持 B/K/M/G/T 单位）
   - date  : 修改日期（支持绝对日期或相对天数/月数/年数）

二、匹配模式（pattern）
   1. 普通匹配（不勾选【正则】）：
      直接输入要包含的字符串（不区分大小写）
      示例：
        • 规则类型 name, 模式 "report" → 匹配所有文件名包含 "report" 的文件
        • 规则类型 ext, 模式 ".txt"   → 匹配所有 .txt 文件
        • 规则类型 path, 模式 "temp"  → 匹配路径中包含 "temp" 的文件

   2. 正则匹配（勾选【正则】）：
      使用 Python 正则表达式（不区分大小写），支持高级模式
      示例：
        • ^test_.*\.py$   → 匹配以 "test_" 开头、.py 结尾的文件名
        • \d{4}-\d{2}     → 匹配包含 "2024-12" 格式日期的路径

三、特殊规则（仅适用于 size 和 date）
   size 示例：
        >10M    → 大于10兆字节
        <1G     → 小于1吉字节
        10K-100K→ 大小在10KB到100KB之间

   date 示例（支持 > 和 < 前缀，表示大于/小于）：
        >2024-01-01        → 修改日期晚于2024年1月1日
        <30d               → 修改时间在最近30天以内（<30d 表示修改日期距今不超过30天）
        >6m                → 修改时间早于6个月前（>6m 表示距今超过6个月）
        <1y                → 修改时间在最近1年内

   （提示：d=天，m=月，y=年；不加前缀默认仅支持精确日期比较不实用，建议结合 > 或 < 使用）

四、黑名单与白名单
   - 白名单（不勾选【黑名单】）：文件必须匹配至少一条白名单规则才会被保留
   - 黑名单（勾选【黑名单】）：文件如果匹配任意一条黑名单规则就会被排除
   - 白名单和黑名单可同时使用：先应用白名单（未匹配则排除），再排除匹配黑名单的文件

五、常用技巧
   - 多个扩展名：使用正则 "\.(jpg|png|gif)$" 匹配图片格式
   - 排除临时文件：黑名单 + 正则 "\.(tmp|log|bak)$"
   - 筛选大文件：size 规则 ">100M"，白名单
   - 筛选近期文件：date 规则 "<30d"，白名单

点击「添加」后规则会立即生效，可以随时在规则列表中查看和删除。
        """
        help_window = tk.Toplevel(self.root)
        help_window.title("使用帮助")
        help_window.geometry("2000x1000")
        help_window.transient(self.root)
        help_window.grab_set()
        text_widget = scrolledtext.ScrolledText(help_window, wrap=tk.WORD, font=self.default_font)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.insert(tk.END, help_text)
        text_widget.config(state=tk.DISABLED)
        close_btn = ttk.Button(help_window, text="关闭", command=help_window.destroy)
        close_btn.pack(pady=10)

    def show_rule_help(self):
        rule_help = "（保留原规则说明文本）"
        help_window = tk.Toplevel(self.root)
        help_window.title("过滤规则说明")
        help_window.geometry("700x700")
        help_window.transient(self.root)
        help_window.grab_set()
        text_widget = scrolledtext.ScrolledText(help_window, wrap=tk.WORD, font=self.default_font)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.insert(tk.END, rule_help)
        text_widget.config(state=tk.DISABLED)
        close_btn = ttk.Button(help_window, text="关闭", command=help_window.destroy)
        close_btn.pack(pady=10)

    def select_scan_dir(self):
        dir_path = filedialog.askdirectory(title="选择扫描目录")
        if dir_path:
            self.path_var.set(dir_path[:50] + "..." if len(dir_path) > 50 else dir_path)
            self.log(f"已选择扫描目录: {dir_path}")

    def start_scan(self):
        scan_path = self.path_var.get()
        if scan_path == "未选择目录":
            messagebox.showwarning("警告", "请先选择扫描目录！")
            return
        if self.is_working:
            messagebox.showwarning("警告", "当前有操作正在进行，请等待完成！")
            return
        self.is_working = True
        self.scan_btn.config(state=tk.DISABLED)
        self.cancel_scan_btn.config(state=tk.NORMAL)
        self.scan_progress['value'] = 0
        self.progress_label.config(text="0%")
        self.log(f"开始扫描目录: {scan_path} (深度: {self.depth_var.get()})")
        self.current_files = []
        self.scanned_data = None
        self.clear_tree()
        self.manager.max_depth = self.depth_var.get()

        def scan_thread():
            try:
                self.scanned_data = self.manager.scan(scan_path, use_cache=self.use_cache_var.get(),
                                                      callback=self.update_scan_progress)
                self.current_files = self.scanned_data['files']
                self.root.after(0, self.on_scan_complete)
            except Exception as e:
                self.root.after(0, lambda: self.on_scan_error(str(e)))
            finally:
                self.root.after(0, self.scan_cleanup)
        threading.Thread(target=scan_thread, daemon=True).start()

    def update_scan_progress(self, progress, file_count):
        self.root.after(0, lambda: self.scan_progress.config(value=progress))
        self.root.after(0, lambda: self.progress_label.config(text=f"{progress}%"))
        self.root.after(0, lambda: self.update_status(f"扫描中... {progress}% ({file_count}个文件)"))

    def cancel_scan(self):
        self.manager.cancel_scan()
        self.update_status("正在取消扫描...")
        self.log("用户取消了扫描操作")

    def scan_cleanup(self):
        self.is_working = False
        self.scan_btn.config(state=tk.NORMAL)
        self.cancel_scan_btn.config(state=tk.DISABLED)

    def on_scan_complete(self):
        if self.scanned_data and not self.manager.scan_cancel:
            file_count = len(self.scanned_data['files'])
            total_size = self.format_size(self.scanned_data['total_size'])
            self.log(f"扫描完成：找到 {file_count} 个文件，总大小 {total_size}")
            self.update_status(f"扫描完成：{file_count} 个文件，总大小 {total_size}")
            self.populate_file_tree(self.current_files)
            self.show_basic_stats()
        else:
            self.log("扫描已取消")
            self.update_status("扫描已取消")

    def on_scan_error(self, error):
        self.log(f"扫描失败：{error}")
        self.update_status(f"扫描失败：{error}")
        messagebox.showerror("错误", f"扫描失败：{error}")

    def format_size(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = int(min(len(size_names)-1, int(math.log(size_bytes, 1024))))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"

    def clear_tree(self):
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        self.selected_files = []
        self.selected_count_var.set("选中: 0 个文件")
        try:
            self.update_counts(total=0, passed=0)
        except Exception:
            pass

    def populate_file_tree(self, files):
        self.clear_tree()
        for i, f in enumerate(files):
            size_str = self.format_size(f['size'])
            mtime_str = datetime.fromtimestamp(f['mtime']).strftime('%Y-%m-%d %H:%M:%S')
            status = f.get('status', '正常')
            tag = 'oddrow' if i % 2 else 'evenrow'
            self.file_tree.insert('', tk.END, values=(f['name'], size_str, f['mime'], mtime_str, f['rel_path'], status),
                                 tags=(tag, f['path']))
        self.log(f"文件列表已更新，共 {len(files)} 个文件")
        try:
            total_all = len(self.scanned_data['files']) if self.scanned_data and 'files' in self.scanned_data else len(files)
            displayed = len(files)
            self.update_counts(total=total_all, passed=displayed)
        except Exception:
            pass

    def refresh_file_list(self):
        if self.current_files:
            self.populate_file_tree(self.current_files)
            self.log("文件列表已刷新")

    def apply_filter(self):
        if not self.current_files:
            messagebox.showwarning("警告", "请先扫描文件！")
            return
        if not self.manager.white_rules and not self.manager.black_rules:
            messagebox.showinfo("提示", "未设置过滤规则，将显示所有文件")
            self.populate_file_tree(self.current_files)
            return
        self.update_status("正在应用过滤规则...")
        self.log("开始应用过滤规则")

        def filter_thread():
            filtered_files = self.manager.filter_files(self.current_files)
            self.root.after(0, lambda: self.on_filter_complete(filtered_files))
        threading.Thread(target=filter_thread, daemon=True).start()

    def on_filter_complete(self, filtered_files):
        self.populate_file_tree(filtered_files)
        self.log(f"过滤完成：{len(filtered_files)} 个文件通过筛选")
        self.update_status(f"过滤完成：{len(filtered_files)} 个文件通过筛选")

    def on_file_select(self, event):
        selected_items = self.file_tree.selection()
        self.selected_files = []
        for item in selected_items:
            values = self.file_tree.item(item, 'values')
            for f in self.current_files:
                if f['rel_path'] == values[4] and f['name'] == values[0]:
                    self.selected_files.append(f)
                    break
        self.selected_count_var.set(f"选中: {len(self.selected_files)} 个文件")
        self.select_all_var.set(len(self.selected_files) == len(self.file_tree.get_children()) and len(self.selected_files) > 0)

    def toggle_select_all(self):
        if self.select_all_var.get():
            self.file_tree.selection_set(self.file_tree.get_children())
        else:
            self.file_tree.selection_remove(self.file_tree.get_children())
        self.on_file_select(None)

    def add_rule(self):
        pattern = self.rule_pattern.get().strip()
        if not pattern:
            messagebox.showwarning("警告", "请输入规则模式！")
            return
        rule_type = self.rule_type.get()
        use_regex = self.regex_var.get()
        is_black = self.black_var.get()
        rule = self.manager.add_rule(rule_type, pattern, is_black, use_regex)
        self.rules_listbox.insert(tk.END, rule['desc'])
        self.rules_listbox.itemconfig(tk.END, {'fg': 'red' if is_black else 'green'})
        self.rule_pattern.delete(0, tk.END)
        self.log(f"添加过滤规则: {rule['desc']}")
        messagebox.showinfo("成功", f"规则添加成功！\n{rule['desc']}")

    def remove_selected_rule(self):
        selected_indices = self.rules_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("警告", "请先选中要删除的规则！")
            return
        for idx in sorted(selected_indices, reverse=True):
            self.rules_listbox.delete(idx)
            if idx < len(self.manager.white_rules):
                del self.manager.white_rules[idx]
            elif idx < len(self.manager.white_rules) + len(self.manager.black_rules):
                del self.manager.black_rules[idx - len(self.manager.white_rules)]
        self.log(f"删除了 {len(selected_indices)} 条规则")
        messagebox.showinfo("成功", f"已删除 {len(selected_indices)} 条选中的规则")

    def clear_rules(self):
        if messagebox.askyesno("确认", "确定要清空所有过滤规则吗？"):
            self.manager.clear_rules()
            self.rules_listbox.delete(0, tk.END)
            self.log("已清空所有过滤规则")
            messagebox.showinfo("成功", "所有过滤规则已清空")

    def sort_tree(self, col):
        # 保留原排序逻辑，仅调整样式无关
        data = []
        try:
            if col == 'size':
                def parse_size_str(s):
                    size, unit = s.split()
                    units = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                    return float(size) * units.get(unit, 1)
                for child in self.file_tree.get_children(''):
                    data.append((parse_size_str(self.file_tree.set(child, col)), child))
            else:
                for child in self.file_tree.get_children(''):
                    data.append((self.file_tree.set(child, col), child))
        except Exception:
            data = [(self.file_tree.set(child, col), child) for child in self.file_tree.get_children('')]
        data.sort(reverse=self.sort_reverse if hasattr(self, 'sort_reverse') else False)
        self.sort_reverse = not self.sort_reverse if hasattr(self, 'sort_reverse') else True
        for index, (val, child) in enumerate(data):
            self.file_tree.move(child, '', index)

    def show_basic_stats(self):
        if not self.scanned_data:
            return
        stats = self.scanned_data['stats']
        total_files = stats['total_files']
        total_size = self.format_size(stats['total_size'])
        stats_text = f"""
📊 文件扫描统计报告
====================
扫描时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
扫描目录：{self.path_var.get()}
扫描深度：{self.manager.max_depth if self.manager.max_depth > 0 else '无限制'}

📈 总体统计：
• 总文件数：{total_files:,} 个
• 总大小：{total_size}

📁 按扩展名分类：
"""
        ext_stats = sorted(stats['by_extension'].items(), key=lambda x: x[1], reverse=True)[:10]
        for ext, count in ext_stats:
            ext = ext if ext else '无扩展名'
            stats_text += f"• {ext}: {count:,} 个\n"
        stats_text += "\n📏 按文件大小分类：\n"
        for size_type, count in stats['by_size'].items():
            stats_text += f"• {size_type}: {count:,} 个\n"
        stats_text += "\n📅 按修改日期分类（近10个月）：\n"
        date_stats = sorted(stats['by_date'].items(), key=lambda x: x[0], reverse=True)[:10]
        for date, count in date_stats:
            stats_text += f"• {date}: {count:,} 个\n"
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete(1.0, tk.END)
        self.stats_text.insert(tk.END, stats_text)
        self.stats_text.config(state=tk.DISABLED)

    def categorize_files(self):
        if not self.current_files:
            messagebox.showwarning("警告", "请先扫描文件！")
            return
        self.update_status("正在分类文件...")
        self.log("开始文件分类")

        def categorize_thread():
            categories = self.manager.categorize(self.current_files)
            self.root.after(0, lambda: self.show_categorize_result(categories))
        threading.Thread(target=categorize_thread, daemon=True).start()

    def show_categorize_result(self, categories):
        cat_window = tk.Toplevel(self.root)
        cat_window.title("📊 文件分类结果")
        cat_window.geometry("800x600")
        cat_window.transient(self.root)
        tree = ttk.Treeview(cat_window, columns=('category', 'count', 'size'), show='headings')
        tree.heading('category', text='分类')
        tree.heading('count', text='文件数')
        tree.heading('size', text='总大小')
        tree.column('category', width=200)
        tree.column('count', width=100)
        tree.column('size', width=150)
        scroll_y = ttk.Scrollbar(cat_window, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll_y.set)
        total_size_all = 0
        for cat_name, cat_info in categories.items():
            files = cat_info['files']
            count = len(files)
            total_size = sum(f['size'] for f in files)
            total_size_all += total_size
            tree.insert('', tk.END, values=(cat_name, count, self.format_size(total_size)))
        tree.insert('', tk.END, values=('总计', len(self.current_files), self.format_size(total_size_all)),
                    tags=('total',))
        tree.tag_configure('total', background='#e9ecef', font=self.title_font)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        def view_category_files():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("警告", "请先选中一个分类！")
                return
            cat_name = tree.item(selected[0], 'values')[0]
            if cat_name == '总计':
                return
            cat_files = categories[cat_name]['files']
            self.populate_file_tree(cat_files)
            cat_window.destroy()
            self.notebook.select(self.files_tab)
            self.log(f"显示分类文件：{cat_name} ({len(cat_files)} 个)")

        view_btn = ttk.Button(cat_window, text="查看选中分类文件", command=view_category_files, style="Accent.TButton")
        view_btn.pack(side=tk.BOTTOM, pady=10)
        self.log(f"文件分类完成，共 {len(categories)} 个分类")
        self.update_status("文件分类完成")

    def find_duplicates(self):
        if not self.current_files:
            messagebox.showwarning("警告", "请先扫描文件！")
            return
        match_type = simpledialog.askstring("查找重复文件", "请选择匹配方式：\n1. name (按文件名)\n2. hash (按文件内容)\n输入 name 或 hash (推荐hash)", initialvalue="hash")
        if not match_type or match_type not in ['name', 'hash']:
            return
        progress_window = tk.Toplevel(self.root)
        progress_window.title("🔍 查找重复文件中...")
        progress_window.geometry("400x100")
        progress_window.transient(self.root)
        progress_window.grab_set()
        progress_label = ttk.Label(progress_window, text="正在分析文件，请稍候...")
        progress_label.pack(pady=10)
        progress_bar = ttk.Progressbar(progress_window, orient=tk.HORIZONTAL, length=300, mode='determinate')
        progress_bar.pack(padx=20, pady=10)

        def find_dup_thread():
            try:
                duplicates = self.manager.find_duplicates(self.current_files, by=match_type,
                                                         progress_callback=lambda p: progress_bar.config(value=p))
                self.root.after(0, lambda: self.show_duplicates_result(duplicates, progress_window))
            except Exception as e:
                self.root.after(0, lambda: self.on_dup_error(str(e), progress_window))
        threading.Thread(target=find_dup_thread, daemon=True).start()

    def show_duplicates_result(self, duplicates, progress_window):
        progress_window.destroy()
        if not duplicates:
            messagebox.showinfo("提示", "未找到重复文件！")
            self.log("未找到重复文件")
            return
        dup_window = tk.Toplevel(self.root)
        dup_window.title(f"🔍 找到 {len(duplicates)} 组重复文件")
        dup_window.geometry("900x600")
        dup_window.transient(self.root)
        tree = ttk.Treeview(dup_window, columns=('group', 'name', 'path', 'size'), show='headings')
        tree.heading('group', text='组号')
        tree.heading('name', text='文件名')
        tree.heading('path', text='路径')
        tree.heading('size', text='大小')
        tree.column('group', width=80)
        tree.column('name', width=200)
        tree.column('path', width=400)
        tree.column('size', width=100)
        scroll_y = ttk.Scrollbar(dup_window, orient=tk.VERTICAL, command=tree.yview)
        scroll_x = ttk.Scrollbar(dup_window, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        for group_idx, group in enumerate(duplicates, 1):
            for f in group:
                tree.insert('', tk.END, values=(group_idx, f['name'], f['path'], self.format_size(f['size'])),
                            tags=(f['path'],))
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)

        def delete_duplicates():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("警告", "请先选中要删除的重复文件！")
                return
            if not messagebox.askyesno("确认删除", "确定要删除选中的重复文件吗？\n文件将被移至回收站！"):
                return
            files_to_delete = []
            for item in selected:
                path = tree.item(item, 'tags')[0]
                for f in self.current_files:
                    if f['path'] == path:
                        files_to_delete.append(f)
                        break
            result = self.manager.delete_files(files_to_delete)
            success_count = len(result['success'])
            error_count = len(result['error'])
            for f in result['success']:
                self.current_files = [x for x in self.current_files if x['path'] != f['path']]
            self.populate_file_tree(self.current_files)
            dup_window.destroy()
            self.log(f"删除重复文件：成功 {success_count} 个，失败 {error_count} 个")
            messagebox.showinfo("结果", f"删除完成！\n成功：{success_count} 个\n失败：{error_count} 个")

        delete_btn = ttk.Button(dup_window, text="🗑️ 删除选中重复文件", command=delete_duplicates, style="Warning.TButton")
        delete_btn.pack(side=tk.BOTTOM, pady=10)
        self.log(f"找到 {len(duplicates)} 组重复文件，共 {sum(len(g) for g in duplicates)} 个重复文件")
        self.update_status(f"找到 {len(duplicates)} 组重复文件")

    def on_dup_error(self, error, progress_window):
        progress_window.destroy()
        self.log(f"查找重复文件失败：{error}")
        messagebox.showerror("错误", f"查找重复文件失败：{error}")

    def batch_rename_dialog(self):
        # 重命名对话框保持原逻辑，仅调整按钮样式等
        if not self.selected_files:
            messagebox.showwarning("警告", "请先选中要重命名的文件！")
            return
        rename_window = tk.Toplevel(self.root)
        rename_window.title("✏️ 批量重命名")
        rename_window.geometry("1000x720")
        rename_window.minsize(800, 600)
        rename_window.transient(self.root)
        rename_window.resizable(True, True)

        ops_frame = ttk.LabelFrame(rename_window, text="重命名操作")
        ops_frame.pack(fill=tk.X, padx=10, pady=10)

        op_types = [
            "replace: 替换文本",
            "regex: 正则替换",
            "case: 大小写转换",
            "add_prefix: 添加前缀",
            "add_suffix: 添加后缀",
            "remove: 移除字符",
            "numbering: 序号命名",
            "clean: 清理特殊字符",
            "date: 添加日期",
            "trim: 去除首尾空格",
            "format: 自定义格式"
        ]
        self.op_type_var = tk.StringVar(value=op_types[0])
        op_type_combo = ttk.Combobox(ops_frame, textvariable=self.op_type_var, values=op_types, state="readonly", width=20)
        op_type_combo.pack(side=tk.LEFT, padx=10, pady=5)

        params_frame = ttk.Frame(ops_frame)
        params_frame.pack(fill=tk.X, padx=10, pady=5)

        def update_params():
            for widget in params_frame.winfo_children():
                widget.destroy()
            op_type = self.op_type_var.get().split(':')[0]
            if op_type == 'replace':
                ttk.Label(params_frame, text="旧文本：").pack(side=tk.LEFT, padx=2)
                self.old_text_var = tk.StringVar()
                ttk.Entry(params_frame, textvariable=self.old_text_var, width=15).pack(side=tk.LEFT, padx=2)
                ttk.Label(params_frame, text="新文本：").pack(side=tk.LEFT, padx=2)
                self.new_text_var = tk.StringVar()
                ttk.Entry(params_frame, textvariable=self.new_text_var, width=15).pack(side=tk.LEFT, padx=2)
            elif op_type == 'regex':
                ttk.Label(params_frame, text="正则表达式：").pack(side=tk.LEFT, padx=2)
                self.regex_pattern_var = tk.StringVar()
                ttk.Entry(params_frame, textvariable=self.regex_pattern_var, width=20).pack(side=tk.LEFT, padx=2)
                ttk.Label(params_frame, text="替换为：").pack(side=tk.LEFT, padx=2)
                self.regex_replace_var = tk.StringVar()
                ttk.Entry(params_frame, textvariable=self.regex_replace_var, width=15).pack(side=tk.LEFT, padx=2)
            elif op_type == 'case':
                ttk.Label(params_frame, text="转换类型：").pack(side=tk.LEFT, padx=2)
                self.case_type_var = tk.StringVar(value="lower")
                case_combo = ttk.Combobox(params_frame, textvariable=self.case_type_var,
                                         values=["lower: 小写", "upper: 大写", "title: 标题", "capitalize: 首字母大写"],
                                         state="readonly", width=15)
                case_combo.pack(side=tk.LEFT, padx=2)
            elif op_type == 'add_prefix':
                ttk.Label(params_frame, text="前缀文本：").pack(side=tk.LEFT, padx=2)
                self.prefix_var = tk.StringVar()
                ttk.Entry(params_frame, textvariable=self.prefix_var, width=30).pack(side=tk.LEFT, padx=2)
            elif op_type == 'add_suffix':
                ttk.Label(params_frame, text="后缀文本：").pack(side=tk.LEFT, padx=2)
                self.suffix_var = tk.StringVar()
                ttk.Entry(params_frame, textvariable=self.suffix_var, width=30).pack(side=tk.LEFT, padx=2)
            elif op_type == 'remove':
                ttk.Label(params_frame, text="起始位置：").pack(side=tk.LEFT, padx=2)
                self.remove_start_var = tk.IntVar(value=0)
                ttk.Spinbox(params_frame, textvariable=self.remove_start_var, from_=0, to=100, width=5).pack(side=tk.LEFT, padx=2)
                ttk.Label(params_frame, text="结束位置：").pack(side=tk.LEFT, padx=2)
                self.remove_end_var = tk.IntVar(value=0)
                ttk.Spinbox(params_frame, textvariable=self.remove_end_var, from_=0, to=100, width=5).pack(side=tk.LEFT, padx=2)
            elif op_type == 'numbering':
                ttk.Label(params_frame, text="序号宽度：").pack(side=tk.LEFT, padx=2)
                self.num_width_var = tk.IntVar(value=3)
                ttk.Spinbox(params_frame, textvariable=self.num_width_var, from_=1, to=10, width=5).pack(side=tk.LEFT, padx=2)
                ttk.Label(params_frame, text="位置：").pack(side=tk.LEFT, padx=2)
                self.num_pos_var = tk.StringVar(value="end")
                num_pos_combo = ttk.Combobox(params_frame, textvariable=self.num_pos_var,
                                           values=["start: 开头", "end: 结尾"], state="readonly", width=10)
                num_pos_combo.pack(side=tk.LEFT, padx=2)
            elif op_type == 'date':
                ttk.Label(params_frame, text="日期格式：").pack(side=tk.LEFT, padx=2)
                self.date_format_var = tk.StringVar(value="%Y%m%d")
                ttk.Entry(params_frame, textvariable=self.date_format_var, width=15).pack(side=tk.LEFT, padx=2)
                ttk.Label(params_frame, text="ℹ").pack(side=tk.LEFT, padx=2)
                ttk.Label(params_frame, text="位置：").pack(side=tk.LEFT, padx=2)
                self.date_pos_var = tk.StringVar(value="prefix")
                date_pos_combo = ttk.Combobox(params_frame, textvariable=self.date_pos_var,
                                            values=["prefix: 前缀", "suffix: 后缀"], state="readonly", width=10)
                date_pos_combo.pack(side=tk.LEFT, padx=2)
            elif op_type == 'format':
                ttk.Label(params_frame, text="格式模板：").pack(side=tk.LEFT, padx=2)
                self.format_template_var = tk.StringVar(value="{name}_{index:03}{ext}")
                fmt_entry = ttk.Entry(params_frame, textvariable=self.format_template_var, width=50, font=self.default_font)
                fmt_entry.pack(side=tk.LEFT, padx=2)
                info_label = ttk.Label(params_frame, text="ℹ")
                info_label.pack(side=tk.LEFT, padx=(4,0))
                ToolTip(info_label, "示例：{name}_{date:%Y-%m-%d}_{index:03}{ext}\n支持占位符：{name},{ext},{index},{date:%Y-%m-%d}\n支持子串：{left:N},{right:N},{mid:start,len}")

        op_type_combo.bind('<<ComboboxSelected>>', lambda e: update_params())
        update_params()

        btn_frame = ttk.Frame(ops_frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        self.operations = []

        ops_listbox = tk.Listbox(btn_frame, height=3, font=self.default_font)
        ops_scroll = ttk.Scrollbar(btn_frame, orient=tk.VERTICAL, command=ops_listbox.yview)
        ops_listbox.configure(yscrollcommand=ops_scroll.set)
        ops_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ops_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def add_operation():
            op_type = self.op_type_var.get().split(':')[0]
            params = {}
            try:
                if op_type == 'replace':
                    params['old'] = self.old_text_var.get()
                    params['new'] = self.new_text_var.get()
                    if not params['old']:
                        raise ValueError("旧文本不能为空")
                elif op_type == 'regex':
                    params['pattern'] = self.regex_pattern_var.get()
                    params['replacement'] = self.regex_replace_var.get()
                    if not params['pattern']:
                        raise ValueError("正则表达式不能为空")
                elif op_type == 'case':
                    params['case'] = self.case_type_var.get().split(':')[0]
                elif op_type == 'add_prefix':
                    params['prefix'] = self.prefix_var.get()
                    if not params['prefix']:
                        raise ValueError("前缀文本不能为空")
                elif op_type == 'add_suffix':
                    params['suffix'] = self.suffix_var.get()
                    if not params['suffix']:
                        raise ValueError("后缀文本不能为空")
                elif op_type == 'remove':
                    params['start'] = self.remove_start_var.get()
                    params['end'] = self.remove_end_var.get()
                    if params['start'] >= params['end'] and params['end'] > 0:
                        raise ValueError("起始位置必须小于结束位置")
                elif op_type == 'numbering':
                    params['width'] = self.num_width_var.get()
                    params['position'] = self.num_pos_var.get().split(':')[0]
                elif op_type == 'date':
                    params['format'] = self.date_format_var.get()
                    params['position'] = self.date_pos_var.get().split(':')[0]
                elif op_type == 'format':
                    params['template'] = self.format_template_var.get()
                    if not params['template'] or not params['template'].strip():
                        raise ValueError("格式模板不能为空")
                self.operations.append({'type': op_type, 'params': params})
                ops_listbox.insert(tk.END, f"{op_type} - {params}")
                preview_rename()
                messagebox.showinfo("成功", "操作已添加！")
            except Exception as e:
                messagebox.showerror("错误", f"添加操作失败：{str(e)}")

        def remove_operation():
            selected = ops_listbox.curselection()
            if selected:
                idx = selected[0]
                ops_listbox.delete(idx)
                del self.operations[idx]
                preview_rename()

        def clear_operations():
            if messagebox.askyesno("确认", "确定要清空所有操作吗？"):
                ops_listbox.delete(0, tk.END)
                self.operations = []
                preview_rename()

        ttk.Button(btn_frame, text="添加操作", command=add_operation, style="Accent.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="移除选中", command=remove_operation).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="清空操作", command=clear_operations).pack(side=tk.LEFT, padx=2)

        preview_frame = ttk.LabelFrame(rename_window, text="重命名预览")
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        preview_tree = ttk.Treeview(preview_frame, columns=('old', 'new', 'status'), show='headings')
        preview_tree.heading('old', text='原文件名')
        preview_tree.heading('new', text='新文件名')
        preview_tree.heading('status', text='状态')
        preview_tree.column('old', width=300)
        preview_tree.column('new', width=300)
        preview_tree.column('status', width=100)
        preview_scroll_y = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=preview_tree.yview)
        preview_scroll_x = ttk.Scrollbar(preview_frame, orient=tk.HORIZONTAL, command=preview_tree.xview)
        preview_tree.configure(yscrollcommand=preview_scroll_y.set, xscrollcommand=preview_scroll_x.set)
        preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        preview_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        preview_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)

        def preview_rename():
            for item in preview_tree.get_children():
                preview_tree.delete(item)
            if not self.operations:
                for f in self.selected_files:
                    preview_tree.insert('', tk.END, values=(f['name'], f['name'], '无变化'))
                return
            results = self.manager.batch_rename(self.selected_files, self.operations, preview=True)
            for res in results:
                preview_tree.insert('', tk.END, values=(res['old'], res['new'], res['status']))
        preview_rename()

        def execute_rename():
            if not self.operations:
                messagebox.showwarning("警告", "请先添加重命名操作！")
                return
            if not messagebox.askyesno("确认", "确定要执行批量重命名吗？\n建议先备份重要文件！"):
                return
            results = self.manager.batch_rename(self.selected_files, self.operations, preview=False)
            success = [r for r in results if r['status'] == '成功']
            failed = [r for r in results if r['status'] == '失败']
            unchanged = [r for r in results if r['status'] == '未修改']
            self.refresh_file_list()
            result_text = f"重命名完成！\n✅ 成功：{len(success)} 个\n❌ 失败：{len(failed)} 个\n➖ 未修改：{len(unchanged)} 个"
            if failed:
                result_text += "\n\n失败详情：\n" + "\n".join([f"• {f['old']} → {f['new']}: {f.get('error', '未知错误')}" for f in failed[:5]])
            messagebox.showinfo("重命名结果", result_text)
            self.log(f"批量重命名完成：成功 {len(success)} 个，失败 {len(failed)} 个")
            rename_window.destroy()

        bottom_btn_frame = ttk.Frame(rename_window)
        bottom_btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(bottom_btn_frame, text="执行重命名", command=execute_rename, style="Accent.TButton").pack(side=tk.RIGHT, padx=5)
        ttk.Button(bottom_btn_frame, text="关闭", command=rename_window.destroy).pack(side=tk.RIGHT, padx=5)

    def extract_files(self):
        if not self.selected_files:
            messagebox.showwarning("警告", "请先选中要提取的文件！")
            return
        dest_path = filedialog.askdirectory(title="选择提取目标目录")
        if not dest_path:
            return
        extract_window = tk.Toplevel(self.root)
        extract_window.title("📤 提取文件选项")
        extract_window.geometry("500x300")
        extract_window.transient(self.root)
        extract_window.grab_set()
        keep_structure_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(extract_window, text="保留原目录结构", variable=keep_structure_var).pack(padx=20, pady=10, anchor=tk.W)
        ttk.Label(extract_window, text="文件冲突处理：").pack(padx=20, pady=5, anchor=tk.W)
        conflict_var = tk.StringVar(value="rename")
        conflict_frame = ttk.Frame(extract_window)
        conflict_frame.pack(padx=30, pady=5, anchor=tk.W)
        ttk.Radiobutton(conflict_frame, text="跳过", variable=conflict_var, value="跳过").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(conflict_frame, text="重命名", variable=conflict_var, value="rename").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(conflict_frame, text="覆盖", variable=conflict_var, value="覆盖").pack(side=tk.LEFT, padx=10)
        ttk.Label(extract_window, text="按以下方式组织文件：").pack(padx=20, pady=5, anchor=tk.W)
        organize_var = tk.StringVar(value="无")
        organize_frame = ttk.Frame(extract_window)
        organize_frame.pack(padx=30, pady=5, anchor=tk.W)
        ttk.Radiobutton(organize_frame, text="无", variable=organize_var, value="无").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(organize_frame, text="类型", variable=organize_var, value="类型").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(organize_frame, text="日期", variable=organize_var, value="日期").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(organize_frame, text="大小", variable=organize_var, value="大小").pack(side=tk.LEFT, padx=10)

        def execute_extract():
            extract_window.destroy()
            progress_window = tk.Toplevel(self.root)
            progress_window.title("📤 提取文件中...")
            progress_window.geometry("400x100")
            progress_window.transient(self.root)
            progress_window.grab_set()
            progress_label = ttk.Label(progress_window, text="正在复制文件，请稍候...")
            progress_label.pack(pady=10)
            progress_bar = ttk.Progressbar(progress_window, orient=tk.HORIZONTAL, length=300, mode='determinate')
            progress_bar.pack(padx=20, pady=10)

            def extract_thread():
                try:
                    result = self.manager.extract(self.selected_files, dest_path,
                                                 keep_structure=keep_structure_var.get(),
                                                 conflict=conflict_var.get(),
                                                 organize_by=organize_var.get() if organize_var.get() != "无" else None,
                                                 callback=lambda p: progress_bar.config(value=p))
                    self.root.after(0, lambda: self.show_extract_result(result, progress_window))
                except Exception as e:
                    self.root.after(0, lambda: self.on_extract_error(str(e), progress_window))
            threading.Thread(target=extract_thread, daemon=True).start()

        btn_frame = ttk.Frame(extract_window)
        btn_frame.pack(side=tk.BOTTOM, pady=20)
        ttk.Button(btn_frame, text="开始提取", command=execute_extract, style="Accent.TButton").pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=extract_window.destroy).pack(side=tk.LEFT, padx=10)

    def show_extract_result(self, result, progress_window):
        progress_window.destroy()
        success = len(result['success'])
        skip = len(result['skip'])
        error = len(result['error'])
        result_text = f"文件提取完成！\n✅ 成功：{success} 个\n➖ 跳过：{skip} 个\n❌ 失败：{error} 个"
        if error:
            result_text += "\n\n失败详情：\n" + "\n".join([f"• {f['name']}: {f.get('error', '未知错误')}" for f in result['error'][:5]])
        messagebox.showinfo("提取结果", result_text)
        self.log(f"文件提取完成：成功 {success} 个，跳过 {skip} 个，失败 {error} 个")

    def on_extract_error(self, error, progress_window):
        progress_window.destroy()
        self.log(f"文件提取失败：{error}")
        messagebox.showerror("错误", f"文件提取失败：{error}")

    def delete_files(self):
        if not self.selected_files:
            messagebox.showwarning("警告", "请先选中要删除的文件！")
            return
        permanent_var = tk.BooleanVar(value=False)
        confirm_window = tk.Toplevel(self.root)
        confirm_window.title("🗑️ 删除文件确认")
        confirm_window.geometry("400x200")
        confirm_window.transient(self.root)
        confirm_window.grab_set()
        ttk.Label(confirm_window, text=f"确定要删除选中的 {len(self.selected_files)} 个文件吗？", font=self.title_font).pack(pady=20)
        ttk.Checkbutton(confirm_window, text="永久删除（不可恢复）", variable=permanent_var).pack(padx=20, pady=10, anchor=tk.W)

        def execute_delete():
            confirm_window.destroy()
            result = self.manager.delete_files(self.selected_files, permanent=permanent_var.get())
            success = len(result['success'])
            error = len(result['error'])
            self.current_files = [f for f in self.current_files if f not in result['success']]
            self.populate_file_tree(self.current_files)
            delete_type = "永久删除" if permanent_var.get() else "移至回收站"
            result_text = f"{delete_type} 完成！\n✅ 成功：{success} 个\n❌ 失败：{error} 个"
            if not permanent_var.get() and success > 0:
                result_text += f"\n\n文件已移至：\n{os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'Desktop', 'FileManager_Trash')}"
            messagebox.showinfo("删除结果", result_text)
            self.log(f"{delete_type} 文件：成功 {success} 个，失败 {error} 个")

        btn_frame = ttk.Frame(confirm_window)
        btn_frame.pack(side=tk.BOTTOM, pady=20)
        ttk.Button(btn_frame, text="确认删除", command=execute_delete, style="Warning.TButton").pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=confirm_window.destroy).pack(side=tk.LEFT, padx=10)

    def analyze_files(self):
        if not self.scanned_data:
            messagebox.showwarning("警告", "请先扫描文件！")
            return
        self.update_status("正在分析文件...")
        self.log("开始深度分析文件")

        def analyze_thread():
            try:
                name_patterns = self.manager.analyzer.analyze_names(self.scanned_data['files'])
                duplicates = self.manager.find_duplicates(self.scanned_data['files'], by='hash')
                report = self.build_analysis_report(name_patterns, duplicates)
                self.root.after(0, lambda: self.show_analysis_report(report))
            except Exception as e:
                self.root.after(0, lambda: self.on_analyze_error(str(e)))
        threading.Thread(target=analyze_thread, daemon=True).start()

    def build_analysis_report(self, name_patterns, duplicates):
        stats = self.scanned_data['stats']
        total_files = stats['total_files']
        total_size = self.format_size(stats['total_size'])
        dup_size = sum(sum(f['size'] for f in group[1:]) for group in duplicates)
        report = f"""
📊 FileManager Pro - 文件深度分析报告
=========================================
生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
扫描目录：{self.path_var.get()}
=========================================

📈 核心统计：
• 总文件数：{total_files:,} 个
• 总大小：{total_size}
• 平均文件大小：{self.format_size(stats['total_size'] // max(total_files, 1))}
• 重复文件组数：{len(duplicates)} 组
• 重复文件数：{sum(len(g) for g in duplicates) - len(duplicates)} 个
"""
        return report

    def show_analysis_report(self, report):
        self.update_status("文件分析完成")
        self.log("文件深度分析完成")
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete(1.0, tk.END)
        self.stats_text.insert(tk.END, report)
        self.stats_text.config(state=tk.DISABLED)
        self.notebook.select(self.stats_tab)
        if messagebox.askyesno("分析完成", "文件分析报告已生成！\n是否保存报告到文件？"):
            save_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("文本文件", "*.txt")])
            if save_path:
                try:
                    with open(save_path, 'w', encoding='utf-8') as f:
                        f.write(report)
                    self.log(f"分析报告已保存到：{save_path}")
                    messagebox.showinfo("成功", f"报告已保存到：{save_path}")
                except Exception as e:
                    self.log(f"保存报告失败：{e}")
                    messagebox.showerror("错误", f"保存报告失败：{e}")

    def on_analyze_error(self, error):
        self.update_status("文件分析失败")
        self.log(f"文件分析失败：{error}")
        messagebox.showerror("错误", f"文件分析失败：{error}")

    def export_results(self):
        if not self.scanned_data:
            messagebox.showwarning("警告", "请先扫描文件！")
            return
        export_path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON文件", "*.json"), ("CSV文件", "*.csv")])
        if not export_path:
            return
        export_type = 'json' if export_path.endswith('.json') else 'csv'
        self.update_status("正在导出结果...")
        self.log(f"开始导出扫描结果为 {export_type} 格式")

        def export_thread():
            try:
                success = self.manager.export_results(self.scanned_data, export_path, export_type)
                self.root.after(0, lambda: self.on_export_complete(success, export_path))
            except Exception as e:
                self.root.after(0, lambda: self.on_export_error(str(e)))
        threading.Thread(target=export_thread, daemon=True).start()

    def on_export_complete(self, success, export_path):
        self.update_status("导出完成")
        if success:
            self.log(f"扫描结果已成功导出到：{export_path}")
            messagebox.showinfo("成功", f"结果已成功导出到：\n{export_path}")
        else:
            self.log("导出扫描结果失败")
            messagebox.showerror("错误", "导出失败！")

    def on_export_error(self, error):
        self.update_status("导出失败")
        self.log(f"导出扫描结果失败：{error}")
        messagebox.showerror("错误", f"导出失败：{error}")


# ========== 程序入口 ==========
if __name__ == "__main__":
    root = TkinterDnD.Tk()
    try:
        root.iconbitmap(default="icon.ico")
    except:
        pass
    app = FileManagerGUI(root)
    root.mainloop()