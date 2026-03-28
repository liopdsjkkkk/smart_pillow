import machine
import time
from machine import Timer, UART

# 配置串口1（接收命令）
uart1 = UART(1, baudrate=9600, tx=17, rx=16)  # 使用 ESP32 的引脚 17 (TX) 和 16 (RX)
# 配置串口2（发送数据到 MP3 模块）
uart2 = UART(2, baudrate=9600, tx=33, rx=32)  # 使用 ESP32 的引脚 33 (TX) 和 32 (RX)

# 设置控制LED灯，使用 ESP32 的 GPIO 2（可选）
led = machine.Pin(2, machine.Pin.OUT)

# 定义命令字节数组
CMD_PLAY = bytearray([0x7E, 0xFF, 0x06, 0x0D, 0x00, 0x00, 0x00, 0xEF])
CMD_SUSPEND = bytearray([0x7E, 0xFF, 0x06, 0x0E, 0x00, 0x00, 0x00, 0xEF])
CMD_LASTSONG = bytearray([0x7E, 0xFF, 0x06, 0x02, 0x00, 0x00, 0x00, 0xEF])  # 3333
CMD_NEXTSONG = bytearray([0x7E, 0xFF, 0x06, 0x01, 0x00, 0x00, 0x00, 0xEF])  # 4444
CMD_VOLUMEP1 = bytearray([0x7E, 0xFF, 0x06, 0x04, 0x00, 0x00, 0x00, 0xEF])  # +
CMD_VOLUMEP2 = bytearray([0x7E, 0xFF, 0x06, 0x05, 0x00, 0x00, 0x00, 0xEF])  # -
QUERY = bytearray([0x7E, 0xFF, 0x06, 0x4C, 0x01, 0x00, 0x00, 0xEF])
CMD_PLAY_COLLECTION = bytearray([0x7E, 0xFF, 0x06, 0x03, 0x00, 0x00, 0x00, 0xEF])
CMD_RANDOM_PLAY = bytearray([0x7E, 0xFF, 0x06, 0x18, 0x00, 0x00, 0x00, 0xEF])
CMD_SINGLE_LOOP = bytearray([0x7E, 0xFF, 0x06, 0x08, 0x00, 0x00, 0x01, 0xEF])
CMD_LIST_LOOP = bytearray([0x7E, 0xFF, 0x06, 0x19, 0x00, 0x00, 0x01, 0xEF])
CMD_SETVOLUME = bytearray([0x7E, 0xFF, 0x06, 0x06, 0x00, 0x00, 0x1E, 0xEF])

# 收藏相关
MAX_NUMS = 10
COLLECTION = [[0, 0] for _ in range(MAX_NUMS)]  # 收藏曲目列表
COLLECTION_COUNT = 0  # 收藏曲目数量
PLAY_COLLECTION_COUNT = 0  # 当前播放的收藏曲目索引
flag_play_collection = 0  # 是否播放收藏
rx_buf = bytearray(30)

# 播放时长控制
play_start_time = None
play_duration_minutes = 30  # 默认30分钟播放
timer = Timer(0)


# 初始化函数
def mp3_init():
    uart2.write(CMD_PLAY)  # 发送播放命令
    time.sleep(0.1)


def stop_playback(t=None):
    global play_start_time
    uart2.write(CMD_SUSPEND)
    print("播放已停止（到达时间限制）")
    play_start_time = None


def setvolume():
    uart2.write(CMD_SETVOLUME)
    print("初始音量设置为5")


def clear_collection():
    global COLLECTION, COLLECTION_COUNT, PLAY_COLLECTION_COUNT
    COLLECTION = [[0, 0] for _ in range(MAX_NUMS)]
    COLLECTION_COUNT = 0
    PLAY_COLLECTION_COUNT = 0
    print("收藏列表已清空")


def reset_play_timer():
    global play_start_time
    play_start_time = time.time()
    timer.deinit()
    timer.init(mode=Timer.ONE_SHOT, period=play_duration_minutes * 60000, callback=stop_playback)


# 解析响应
def parse_response(buf):
    global COLLECTION, COLLECTION_COUNT
    if buf[0] == 0x7E and buf[3] == 0x4C and buf[9] == 0xEF and COLLECTION_COUNT < MAX_NUMS:
        COLLECTION[COLLECTION_COUNT][0] = buf[5]
        COLLECTION[COLLECTION_COUNT][1] = buf[6]
        COLLECTION_COUNT += 1


# 播放收藏功能
def play_collection():
    global PLAY_COLLECTION_COUNT
    # 更新播放集合曲目的索引
    if PLAY_COLLECTION_COUNT >= COLLECTION_COUNT:
        PLAY_COLLECTION_COUNT = 0  # 循环播放
    CMD_PLAY_COLLECTION[5] = COLLECTION[PLAY_COLLECTION_COUNT][0]
    CMD_PLAY_COLLECTION[6] = COLLECTION[PLAY_COLLECTION_COUNT][1]
    uart2.write(CMD_PLAY_COLLECTION)  # 播放收藏的曲目


# 收到 "a" 命令时执行的操作
def collect():
    uart2.write(QUERY)
    time.sleep(0.2)
    if uart2.any():
        response = uart2.read()
        parse_response(response)
    print("已处理 QUERY 并尝试收藏")


def process_uart_command():
    global PLAY_COLLECTION_COUNT, flag_play_collection, COLLECTION_COUNT

    if uart1.any():
        command = uart1.read().decode('utf-8').strip()
        print("Received command:", command)

        if command == "1111":
            flag_play_collection = 0
            uart2.write(CMD_PLAY)
        elif command == "2222":
            uart2.write(CMD_SUSPEND)
        elif command == "3333":
            if flag_play_collection:
                PLAY_COLLECTION_COUNT = (PLAY_COLLECTION_COUNT - 1) % COLLECTION_COUNT
                play_collection()
            else:
                uart2.write(CMD_LASTSONG)
        elif command == "4444":
            if flag_play_collection:
                PLAY_COLLECTION_COUNT = (PLAY_COLLECTION_COUNT + 1) % COLLECTION_COUNT
                play_collection()
            else:
                uart2.write(CMD_NEXTSONG)
        elif command == "5555":
            uart2.write(CMD_VOLUMEP1)
            print("Received command:", command)
        elif command == "6666":
            uart2.write(CMD_VOLUMEP2)
        elif command == "a":
            uart2.write(QUERY)
            time.sleep(0.2)
            if uart2.any():
                response = uart2.read()
                parse_response(response)
                COLLECTION_COUNT = COLLECTION_COUNT + 1
        elif command == "b":
            flag_play_collection = 1
            play_collection()

        time.sleep(0.1)



