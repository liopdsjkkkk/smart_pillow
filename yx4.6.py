import machine
import time
from machine import UART, Pin

class SoundSystem:
    """音响控制系统 - 用于ESP32控制MP3-TF-16P模块"""
    
    def __init__(self, uart1_tx=17, uart1_rx=16, uart2_tx=33, uart2_rx=32, busy_pin=4):
        # 配置串口
        self.uart1 = UART(1, baudrate=9600, tx=uart1_tx, rx=uart1_rx, timeout=10)
        self.uart2 = UART(2, baudrate=9600, tx=uart2_tx, rx=uart2_rx, timeout=10)
        
        # 忙碌检测引脚
        self.busy_pin = Pin(busy_pin, Pin.IN, Pin.PULL_UP)
        
        # 定义命令字节数组
        self.CMD_PLAY = bytearray([0x7E, 0xFF, 0x06, 0x0D, 0x00, 0x00, 0x00, 0xEF])
        self.CMD_PAUSE = bytearray([0x7E, 0xFF, 0x06, 0x0E, 0x00, 0x00, 0x00, 0xEF])
        self.CMD_STOP = bytearray([0x7E, 0xFF, 0x06, 0x16, 0x00, 0x00, 0x00, 0xEF])
        self.CMD_LAST_SONG = bytearray([0x7E, 0xFF, 0x06, 0x02, 0x00, 0x00, 0x00, 0xEF])
        self.CMD_NEXT_SONG = bytearray([0x7E, 0xFF, 0x06, 0x01, 0x00, 0x00, 0x00, 0xEF])
        self.CMD_VOLUME_UP = bytearray([0x7E, 0xFF, 0x06, 0x04, 0x00, 0x00, 0x00, 0xEF])
        self.CMD_VOLUME_DOWN = bytearray([0x7E, 0xFF, 0x06, 0x05, 0x00, 0x00, 0x00, 0xEF])
        self.CMD_QUERY_STATUS = bytearray([0x7E, 0xFF, 0x06, 0x42, 0x00, 0x00, 0x00, 0xEF])
        self.CMD_QUERY_TRACK = bytearray([0x7E, 0xFF, 0x06, 0x4C, 0x01, 0x00, 0x00, 0xEF])
        
        # 收藏系统
        self.MAX_COLLECTIONS = 20
        self.collections = []  # 存储收藏的曲目编号
        self.current_collection_index = 0
        self.collection_mode = False
        
        # 控制参数
        self.last_command_time = 0
        self.command_cooldown = 0.3
        self.last_unknown_time = 0
        self.unknown_cooldown = 2.0
        
        # 状态变量
        self.is_playing = False
        self.current_volume = 15  # 默认音量(0-30)
        self.current_track = 1  # 默认从第1首开始
        
        # 曲目跟踪
        self.track_counter = 1  # 当前曲目计数器
        self.max_tracks = 100  # 假设最大曲目数
        
        # 初始化MP3模块
        self._mp3_init()
        
        print("音响系统初始化完成")

    def _mp3_init(self):
        """初始化MP3模块"""
        # 设置初始音量
        self.set_volume(self.current_volume)
        time.sleep(0.1)
        
        # 停止播放
        self.uart2.write(self.CMD_STOP)
        time.sleep(0.1)
        
        print("MP3模块初始化完成")

    def set_volume(self, volume):
        """设置音量(0-30)"""
        if 0 <= volume <= 30:
            cmd = bytearray([0x7E, 0xFF, 0x06, 0x06, 0x00, 0x00, volume, 0xEF])
            self.uart2.write(cmd)
            self.current_volume = volume
            print(f"音量设置为: {volume}")
            return True
        return False

    def play_track(self, track_num):
        """播放指定曲目"""
        if 1 <= track_num <= 65535:
            high_byte = (track_num >> 8) & 0xFF
            low_byte = track_num & 0xFF
            cmd = bytearray([0x7E, 0xFF, 0x06, 0x03, 0x00, high_byte, low_byte, 0xEF])
            self.uart2.write(cmd)
            self.current_track = track_num
            self.track_counter = track_num  # 更新曲目计数器
            self.is_playing = True
            print(f"播放曲目: {track_num}")
            return True
        return False

    def play_next(self):
        """播放下一曲，并更新当前曲目跟踪"""
        self.uart2.write(self.CMD_NEXT_SONG)
        self.track_counter = (self.track_counter % self.max_tracks) + 1
        self.current_track = self.track_counter
        self.is_playing = True
        print(f"下一曲，当前曲目: {self.current_track}")
        return True

    def play_prev(self):
        """播放上一曲，并更新当前曲目跟踪"""
        self.uart2.write(self.CMD_LAST_SONG)
        self.track_counter = self.track_counter - 1 if self.track_counter > 1 else self.max_tracks
        self.current_track = self.track_counter
        self.is_playing = True
        print(f"上一曲，当前曲目: {self.current_track}")
        return True

    def add_collection(self, track_num=None):
        """添加当前曲目到收藏 - 增强版本"""
        if len(self.collections) >= self.MAX_COLLECTIONS:
            print("收藏已满，无法添加")
            return False
            
        # 如果未指定曲目，使用当前跟踪的曲目
        if track_num is None:
            track_num = self.current_track
            
        # 确保曲目编号有效
        if track_num is None or track_num <= 0:
            print("收藏失败: 无效的当前曲目编号")
            # 尝试使用曲目计数器作为备选
            if self.track_counter > 0:
                track_num = self.track_counter
                print(f"使用曲目计数器: {track_num}")
            else:
                # 最后备选：使用默认值1
                track_num = 1
                print(f"使用默认曲目: {track_num}")
            
        if track_num and track_num not in self.collections:
            self.collections.append(track_num)
            print(f"收藏成功! 曲目: {track_num}, 收藏数: {len(self.collections)}")
            print(f"当前收藏列表: {self.collections}")
            return True
        elif track_num in self.collections:
            print(f"曲目 {track_num} 已在收藏列表中")
            return False
            
        print(f"收藏失败: 曲目编号 {track_num} 无效")
        return False

    def play_collection(self, index=None):
        """播放收藏曲目"""
        if not self.collections:
            print("收藏列表为空，无法播放收藏")
            return False
            
        if index is None:
            index = self.current_collection_index
        else:
            self.current_collection_index = index
            
        if 0 <= index < len(self.collections):
            track = self.collections[index]
            self.collection_mode = True
            self.current_collection_index = index
            print(f"播放收藏第{index+1}首，共{len(self.collections)}首，曲目: {track}")
            return self.play_track(track)
        else:
            print(f"收藏索引 {index} 超出范围")
            return False

    def next_collection(self):
        """播放下一首收藏"""
        if not self.collections:
            print("收藏列表为空")
            return False
            
        self.current_collection_index = (self.current_collection_index + 1) % len(self.collections)
        print(f"切换到下一首收藏，索引: {self.current_collection_index}")
        return self.play_collection()

    def prev_collection(self):
        """播放上一首收藏"""
        if not self.collections:
            print("收藏列表为空")
            return False
            
        self.current_collection_index = (self.current_collection_index - 1) % len(self.collections)
        if self.current_collection_index < 0:
            self.current_collection_index = len(self.collections) - 1
        print(f"切换到上一首收藏，索引: {self.current_collection_index}")
        return self.play_collection()

    def clear_collections(self):
        """清空收藏列表"""
        self.collections.clear()
        self.current_collection_index = 0
        self.collection_mode = False
        print("收藏列表已清空")

    def get_status(self):
        """获取播放状态"""
        return {
            'playing': self.is_playing,
            'volume': self.current_volume,
            'current_track': self.current_track,
            'track_counter': self.track_counter,
            'collections_count': len(self.collections),
            'collections': self.collections,
            'current_collection_index': self.current_collection_index,
            'collection_mode': self.collection_mode
        }

    def process_uart_command(self):
        """处理UART命令的主函数"""
        try:
            current_time = time.time()
            
            # 检查冷却时间
            if current_time - self.last_command_time < self.command_cooldown:
                return False
                
            if self.uart1.any():
                data = self.uart1.read()
                command = self._safe_decode(data)
                
                if command and self._is_valid_command(command):
                    # 更新最后命令时间
                    self.last_command_time = current_time
                    
                    # 执行命令
                    return self._execute_command(command)
                    
        except Exception as e:
            print("处理UART命令错误:", e)
            
        return False

    # 添加process_command方法作为别名，确保兼容性
    def process_command(self):
        """process_command的别名，兼容旧代码"""
        return self.process_uart_command()

    def _safe_decode(self, data):
        """安全解码数据"""
        try:
            return data.decode('utf-8').strip()
        except:
            try:
                return data.decode('ascii', 'ignore').strip()
            except:
                return ""

    def _is_valid_command(self, command):
        """验证命令有效性"""
        if not command or len(command) > 20:
            return False
            
        # 检查是否只包含可打印ASCII字符
        if not all(32 <= ord(c) <= 126 for c in command):
            return False
            
        # 有效的命令列表
        valid_commands = {
            "1111", "2222", "3333", "4444", "5555", "6666", 
            "a", "8", "last", "next", "play", "pause", "stop",
            "lastsong", "nextsong", "volumep1", "volumep2",
            "collect", "play_collection", "next_collection", "prev_collection",
            "clear_collection", "status", "volume_up", "volume_down"
        }
        
        return command in valid_commands

    def _execute_command(self, command):
        """执行具体命令"""
        try:
            if command == "1111" or command == "play":
                self.uart2.write(self.CMD_PLAY)
                self.is_playing = True
                print("播放音乐")
                return True
                
            elif command == "2222" or command == "pause":
                self.uart2.write(self.CMD_PAUSE)
                self.is_playing = False
                print("暂停音乐")
                return True
                
            elif command == "3333" or command == "next" or command == "nextsong":
                return self.play_next()  # 使用增强的下一曲方法
                
            elif command == "4444" or command == "last" or command == "lastsong":
                return self.play_prev()  # 使用增强的上一曲方法
                
            elif command == "5555" or command == "volumep1" or command == "volume_up":
                self.uart2.write(self.CMD_VOLUME_UP)
                self.current_volume = min(30, self.current_volume + 1)
                print(f"音量增加至: {self.current_volume}")
                return True
                
            elif command == "6666" or command == "volumep2" or command == "volume_down":
                self.uart2.write(self.CMD_VOLUME_DOWN)
                self.current_volume = max(0, self.current_volume - 1)
                print(f"音量减少至: {self.current_volume}")
                return True
                
            elif command == "a" or command == "collect":
                success = self.add_collection()
                if success:
                    print("收藏成功")
                else:
                    print("收藏失败")
                return success
                
            elif command == "8" or command == "play_collection":
                return self.play_collection()
                
            elif command == "next_collection":
                return self.next_collection()
                
            elif command == "prev_collection":
                return self.prev_collection()
                
            elif command == "clear_collection":
                self.clear_collections()
                return True
                
            elif command == "status":
                status = self.get_status()
                print(f"音响状态: {status}")
                return True
                
            else:
                print(f"未知命令: {command}")
                return False
                
        except Exception as e:
            print(f"执行命令 {command} 时出错: {e}")
            return False

# 全局实例
sound_system = None

def init_sound_system(tx1=17, rx1=16, tx2=33, rx2=32, busy_pin=4):
    """初始化全局音响系统实例"""
    global sound_system
    sound_system = SoundSystem(tx1, rx1, tx2, rx2, busy_pin)
    return sound_system

def get_sound_system():
    """获取音响系统实例"""
    global sound_system
    if sound_system is None:
        raise Exception("音响系统未初始化，请先调用 init_sound_system()")
    return sound_system

# 独立运行测试
if __name__ == "__main__":
    system = init_sound_system()
    print("音响系统独立运行中...")
    while True:
        system.process_uart_command()
        time.sleep(0.1)


