import time
import utime
from machine import Pin, PWM, reset, ADC, UART, Timer
import network
from umqttsimple import MQTTClient
import ujson
import math
import json
import yx

# =============================================
# 软件配置
# =============================================
MQTT_SERVER = "192.168.222.24"
BODY_STATE_TOPIC = "sleep_detect"
SOUND_SYS_TOPIC = "music"
SOUND_DETECT_TOPIC = "sound_detect"
AIRBAG_TOPIC = "qinang"
CLIENT_ID = "esp32"
KEEP_ALIVE = 60
WIFI_SSID = '小兔子乖乖'
WIFI_PASS = '12345678'

# 音响默认配置
DEFAULT_MODE = "single_loop"
DEFAULT_TIME_MIN = 120

# 全局变量
mqtt_client = None
sound_system = None
yx_mode = DEFAULT_MODE
yx_time_min = DEFAULT_TIME_MIN
yx_start_time = None
yx_config_updated = False
sleep_detection_enabled = True

# =============================================
# 硬件引脚配置
# =============================================
led = Pin(0, Pin.OUT)  # GPIO0
led.value(1)

# ---------------------------------------------------
# 6个气泵的电机驱动引脚
# ---------------------------------------------------

# 气泵1（4路电机模块）
EN1 = PWM(Pin(14, Pin.OUT), freq=500)  # 调速
IN1 = Pin(13, Pin.OUT)  # 方向
IN2 = Pin(27, Pin.OUT)

# 气泵2（4路电机模块）
EN2 = PWM(Pin(22, Pin.OUT), freq=500)
IN3 = Pin(23, Pin.OUT)
IN4 = Pin(26, Pin.OUT)

# 气泵3（4路电机模块）
EN3 = PWM(Pin(18, Pin.OUT), freq=500)
IN5 = Pin(19, Pin.OUT)
IN6 = Pin(5, Pin.OUT)

# 气泵4（4路电机模块）
EN4 = PWM(Pin(33, Pin.OUT), freq=500)
IN7 = Pin(32, Pin.OUT)
IN8 = Pin(25, Pin.OUT)

# 气泵5（2路电机模块，使用ENA）
EN5 = PWM(Pin(15, Pin.OUT), freq=500)  # ENA
IN9 = Pin(4, Pin.OUT,value=0)  
IN10 = Pin(2,Pin.OUT,value=0) 

# 气泵6（2路电机模块，使用ENB）
EN6 = PWM(Pin(12, Pin.OUT), freq=500)  # ENB
IN11 = Pin(21, Pin.OUT)  # 方向1
IN12 = Pin(16, Pin.OUT)  # 方向2

#使用气泵方向引脚2作为继电器控制
relay1_pin = IN2  # 复用IN2作为继电器1
relay2_pin = IN4  # 复用IN4作为继电器2
relay3_pin = IN6  # 复用IN6作为继电器3
relay4_pin = IN8  # 复用IN8作为继电器4
relay5_pin = IN10  # 复用IN10作为继电器5
relay6_pin = IN12  # 复用IN12作为继电器6

PUMP_EN_PINS = [EN1, EN2, EN3, EN4, EN5, EN6]
PUMP_IN1_PINS = [IN1, IN3, IN5, IN7, IN9, IN11]  # 方向引脚1
PUMP_IN2_PINS = [IN2, IN4, IN6, IN8, IN10, IN12]  # 方向引脚2（复用为继电器）
RELAY_PINS = [relay1_pin, relay2_pin, relay3_pin, relay4_pin, relay5_pin, relay6_pin]

# 全局变量
intervention_stage = 0
last_action_time = 0
cooldown_interval = 3
last_reset_day = None


# =============================================
# 初始化函数
# =============================================
def init_motors_safe():
    """初始化所有输出为安全状态"""
    # 关闭所有方向引脚
    for i in range(6):
        PUMP_IN1_PINS[i].off()
        PUMP_IN2_PINS[i].off()
    IN9.off;
    IN10.off;
    # 停止所有气泵
    for pwm in PUMP_EN_PINS:
        pwm.duty(0)

    print("6路系统已初始化为安全状态")


# =============================================
# WiFi连接
# =============================================
def connect_wifi():
    global mqtt_client, sound_system
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('正在连接 WiFi...')
        wlan.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(15):
            if wlan.isconnected():
                break
            time.sleep(1)
    if wlan.isconnected():
        print('连接成功，IP:', wlan.ifconfig()[0])
        try:
            mqtt_client = MQTTClient(CLIENT_ID, MQTT_SERVER, keepalive=KEEP_ALIVE)
            mqtt_client.set_callback(mqtt_callback)
            mqtt_client.connect()
            mqtt_client.subscribe(SOUND_SYS_TOPIC)
            mqtt_client.subscribe(BODY_STATE_TOPIC)
            mqtt_client.subscribe(AIRBAG_TOPIC)
            mqtt_client.subscribe(SOUND_DETECT_TOPIC)

            # 初始化音响系统
            sound_system = yx.init_sound_system(tx1=4, rx1=3, tx2=17, rx2=34, busy_pin=35)
            print("音响系统初始化完成")

        except Exception as e:
            print("MQTT连接失败:", e)
        return True
    print('WiFi连接失败')
    return False


# =============================================
# 核心控制函数 
# =============================================
def motor_control(motor_num, direction, speed=512):
    """
    控制指定电机的转动
    :param motor_num: 1-6
    :param direction: 'STOP', 'CW' (正转/充气), 'CCW' (反转/抽气)
    :param speed: PWM占空比 0-1023
    """
    if 1 <= motor_num <= 6:
        idx = motor_num - 1
        en = PUMP_EN_PINS[idx]
        in1 = PUMP_IN1_PINS[idx]
        in2 = PUMP_IN2_PINS[idx]  # 这个引脚复用为继电器

        if direction == 'STOP':
            in1.off()
            in2.off()  # 关闭继电器
            en.duty(0)
            print(f"电机{motor_num} 停止")
        elif direction == 'CW':  # 正转（充气）
            in1.on()  # 方向1=1
            in2.off()  # 方向2=0，同时关闭继电器
            en.duty(speed)
            print(f"电机{motor_num} 正转 (充气)，速度: {speed}")
        elif direction == 'CCW':  # 反转（如果需要抽气）
            in1.off()  # 方向1=0
            in2.on()  # 方向2=1，但这里我们不会在反转时打开继电器
            en.duty(speed)
            print(f"电机{motor_num} 反转，速度: {speed}")
        else:
            print(f"错误方向指令: {direction}")
    else:
        print(f"错误电机编号: {motor_num}")
        
def inflate_pump(pump_num, duration=20):
    """控制指定气泵充气"""
    print(f"气泵{pump_num} 充气 {duration}秒")
    motor_control(pump_num, 'CW', 1000)  # 开始正转
    time.sleep(duration)
    motor_control(pump_num, 'STOP')  # 停止
    print(f"气泵{pump_num} 充气完成")


def deflate_pump(pump_num, duration=15):
    """控制指定气泵放气"""
    print(f"气泵{pump_num} 放气 {duration}秒")
    motor_control(pump_num, 'STOP')  # 确保电机停止

    # 打开对应继电器的放气阀
    if 1 <= pump_num <= 6:
        idx = pump_num - 1
        RELAY_PINS[idx].on()  # 打开继电器（放气）
        time.sleep(duration)
        RELAY_PINS[idx].off()  # 关闭继电器

    print(f"气泵{pump_num} 放气完成")


def inflate_all(duration=30):
    """同时充气所有气泵"""
    print(f"所有气泵充气 {duration}秒")
    for i in range(1, 7):
        motor_control(i, 'CW', 512)
    time.sleep(duration)
    for i in range(1, 7):
        motor_control(i, 'STOP')
    print("所有气泵充气完成")


def deflate_all(duration=15):
    """同时放气所有气泵"""
    print(f"所有气泵放气 {duration}秒")
    # 先停止所有电机
    for i in range(1, 7):
        motor_control(i, 'STOP')
    # 打开所有放气阀
    for relay in RELAY_PINS:
        relay.on()
    time.sleep(duration)
    # 关闭所有放气阀
    for relay in RELAY_PINS:
        relay.off()
    print("所有气泵放气完成")


# =============================================
# 音乐控制函数 - 
# =============================================
def control_music(action, params=None):
    """控制音乐播放 - 修复收藏问题"""
    global sound_system

    if sound_system is None:
        print("音响系统未初始化")
        return False

    try:
        if action == "play":
            return sound_system.play()

        elif action == "pause":
            return sound_system.pause()

        elif action == "stop":
            return sound_system.stop()

        elif action == "next":
            return sound_system.play_next()

        elif action == "prev":
            return sound_system.play_prev()

        elif action == "volume_up":
            return sound_system.volume_up()

        elif action == "volume_down":
            return sound_system.volume_down()

        elif action == "set_volume" and params is not None:
            volume = params.get("volume")
            if volume is not None:
                success = sound_system.set_volume(volume)
                if success:
                    print(f"音量设置为: {volume}")
                return success

        elif action == "collect":
            # 重要修改：使用改进的收藏方法
            success = sound_system.add_collection()
            if success:
                print("收藏当前曲目成功")
                # 发送收藏成功消息到MQTT
                if mqtt_client:
                    status = sound_system.get_status()
                    mqtt_client.publish(SOUND_SYS_TOPIC + "/collection",
                                        ujson.dumps({
                                            "action": "added",
                                            "track": status['current_track'],
                                            "collections": status['collections']
                                        }))
            else:
                print("收藏当前曲目失败")
            return success

        elif action == "play_collection":
            index = params.get("index") if params else None
            success = sound_system.play_collection(index)
            if success:
                print("播放收藏列表")
            return success

        elif action == "next_collection":
            success = sound_system.next_collection()
            if success:
                print("下一首收藏")
            return success

        elif action == "prev_collection":
            success = sound_system.prev_collection()
            if success:
                print("上一首收藏")
            return success

        elif action == "clear_collection":
            sound_system.clear_collections()
            print("清空收藏")
            return True

        elif action == "status":
            status = sound_system.get_status()
            print(f"音响状态: {status}")
            # 发布状态到MQTT
            if mqtt_client:
                mqtt_client.publish(SOUND_SYS_TOPIC + "/status", ujson.dumps(status))
            return True

        else:
            print(f"未知的音乐控制命令: {action}")
            return False

    except Exception as e:
        print(f"音乐控制错误: {e}")
        return False


# =============================================
# 睡眠检测控制函数 - 
# =============================================
def start_sleep_detection():
    """开始睡眠检测"""
    global sleep_detection_enabled, monitor
    if not sleep_detection_enabled:
        sleep_detection_enabled = True
        monitor.reset_detection()  # 重置检测状态
        print("睡眠检测已启动")
        return True
    return False


def stop_sleep_detection():
    """停止睡眠检测并生成报告"""
    global sleep_detection_enabled, monitor
    if sleep_detection_enabled:
        sleep_detection_enabled = False
        report = monitor.generate_report()
        print("睡眠检测已停止，报告已生成")
        return report
    return None


def is_sleep_detection_enabled():
    """检查睡眠检测是否启用"""
    return sleep_detection_enabled


# =============================================
# 干预控制函数
# =============================================
def perform_intervention(stage):
    """执行干预动作"""
    global intervention_stage

    if stage == 1:
        print("第1次干预（左侧1-3）")
        # 气泵1-3充气20秒
        inflate_pump(1, 20)
        inflate_pump(2, 20)
        inflate_pump(3, 20)

        # 等待20秒
        time.sleep(20)

        # 放气15秒
        deflate_pump(1, 15)
        deflate_pump(2, 15)
        deflate_pump(3, 15)

        intervention_stage = 1

    elif stage == 2:
        print("第2次干预（右侧4-6）")
        # 气泵4-6充气20秒
        inflate_pump(4, 20)
        inflate_pump(5, 20)
        inflate_pump(6, 20)

        # 等待20秒
        time.sleep(20)

        # 放气15秒
        deflate_pump(4, 15)
        deflate_pump(5, 15)
        deflate_pump(6, 15)

        intervention_stage = 2


# =============================================
# MQTT回调处理函数 
# =============================================
def mqtt_callback(topic, msg):
    global last_action_time, intervention_stage, yx_mode, yx_time_min, yx_start_time, yx_config_updated
    global sleep_detection_enabled

    try:
        topic_str = topic.decode('utf-8') if isinstance(topic, bytes) else topic
        data = ujson.loads(msg)
        print("收到消息 - 主题:", topic_str, "数据:", data)

        if topic_str == SOUND_DETECT_TOPIC:
            if data.get("status") == "hansheng":
                current_time = time.time()
                if current_time - last_action_time < cooldown_interval:
                    print("气泵冷却中，跳过干预")
                    return
                last_action_time = current_time

                if led:
                    led.value(0)

                deflate_all(2)  # 干预前放气安全处理

                if intervention_stage == 0:
                    perform_intervention(1)
                elif intervention_stage == 1:
                    perform_intervention(2)
                elif intervention_stage == 2:
                    print("已完成两次干预，冷却中...")

                if led:
                    led.value(1)

        elif topic_str == AIRBAG_TOPIC:
            command = data.get("action")
            print("收到气囊命令:", command)

            duration = data.get("duration", 0)

            if command == "inflate_all":
                if duration > 0:
                    deflate_all(2)  # 先放气
                    inflate_all(duration)
                else:
                    deflate_all(2)  # 先放气
                    inflate_all()

            elif command == "deflate_all":
                if duration > 0:
                    deflate_all(duration)
                else:
                    deflate_all()

            elif command.startswith("inflate."):
                try:
                    pump_num = int(command.split('.')[1])
                    if 1 <= pump_num <= 6:
                        if duration > 0:
                            deflate_all(2)  # 先放气
                            inflate_pump(pump_num, duration)
                        else:
                            deflate_all(2)  # 先放气
                            inflate_pump(pump_num)
                    else:
                        print(f"错误：不支持的气泵编号 {pump_num}")
                except (IndexError, ValueError):
                    print(f"错误：无效的指令格式 '{command}'，请使用 'inflate.1' 到 'inflate.6'")

            elif command.startswith("deflate."):
                try:
                    pump_num = int(command.split('.')[1])
                    if 1 <= pump_num <= 6:
                        if duration > 0:
                            deflate_pump(pump_num, duration)
                        else:
                            deflate_pump(pump_num)
                    else:
                        print(f"错误：不支持的气泵编号 {pump_num}")
                except (IndexError, ValueError):
                    print(f"错误：无效的指令格式 '{command}'，请使用 'deflate.1' 到 'deflate.6'")

            elif command == "reset":
                intervention_stage = 0
                print("干预状态已手动重置")

            else:
                print(f"未知的气囊命令: {command}")

        elif topic_str == SOUND_SYS_TOPIC:
            action = data.get("action")
            params = data.get("params", {})
            print("收到音乐命令:", action, "参数:", params)

            # 处理音乐控制命令
            control_music(action, params)

    except Exception as e:
        print("MQTT处理错误:", e)


# =============================================
# 其他辅助函数
# =============================================
def auto_reset_check():
    """每天9点自动重置干预状态"""
    global last_reset_day, intervention_stage
    t = time.localtime()
    if t[3] == 9 and last_reset_day != t[2]:
        intervention_stage = 0
        last_reset_day = t[2]
        print("每天9点自动重置干预状态")


def check_play_duration():
    """检查播放时长，根据需要停止播放"""
    global yx_start_time, yx_time_min, sound_system

    if yx_start_time is not None and sound_system is not None:
        current_time = time.time()
        elapsed_minutes = (current_time - yx_start_time) / 60

        if elapsed_minutes >= yx_time_min:
            print(f"播放时长达到{yx_time_min}分钟，停止播放")
            sound_system.stop()
            yx_start_time = None


# 睡眠监测类
class Config:
    SENSOR_PINS = [36, 37, 38]
    SAMPLING_PERIOD_MS = 100
    BUFFER_SIZE = 300
    SLEEP_THRESHOLD = 500
    SENSOR_WEIGHTS = [0.3, 0.4, 0.3]


class SleepMonitor:
    def __init__(self):
        self.sensors = self.init_sensors()
        self.buffer = [[0] * Config.BUFFER_SIZE for _ in range(3)]
        self.index = 0
        self.sleep_stage = "AWAKE"
        self.last_stage = None
        self.stable_counter = 0
        self.sleep_start_time = None
        self.light_sleep_duration = 0
        self.deep_sleep_duration = 0
        self.in_sleep_session = False
        self.detection_start_time = None
        self.total_detection_time = 0

    def init_sensors(self):
        sensor_list = []
        for pin in Config.SENSOR_PINS:
            adc = ADC(Pin(pin))
            adc.atten(ADC.ATTN_11DB)
            sensor_list.append(adc)
        return sensor_list

    def reset_detection(self):
        self.sleep_stage = "AWAKE"
        self.last_stage = None
        self.stable_counter = 0
        self.sleep_start_time = None
        self.light_sleep_duration = 0
        self.deep_sleep_duration = 0
        self.in_sleep_session = False
        self.detection_start_time = time.time()
        self.total_detection_time = 0
        print("睡眠检测状态已重置")

    def update(self):
        global sleep_detection_enabled
        if not sleep_detection_enabled:
            return

        values = [s.read() for s in self.sensors]
        for i in range(3):
            self.buffer[i][self.index] = values[i]
        self.index = (self.index + 1) % Config.BUFFER_SIZE
        self.analyze_sleep(values)

    def analyze_sleep(self, current_values):
        avg_pressure = sum(w * v for w, v in zip(Config.SENSOR_WEIGHTS, current_values))
        variability = self.calculate_variability()
        current_time = time.time()

        new_stage = self.sleep_stage
        if avg_pressure < Config.SLEEP_THRESHOLD:
            new_stage = "NO_PERSON"
            self.stable_counter = 0
        elif variability > 30:
            new_stage = "AWAKE"
            self.stable_counter = 0
        elif variability > 10:
            new_stage = "LIGHT_SLEEP"
            self.stable_counter = 0
        else:
            self.stable_counter += 1
            new_stage = "DEEP_SLEEP" if self.stable_counter > 600 else "LIGHT_SLEEP"

        if new_stage != self.sleep_stage:
            if self.in_sleep_session and new_stage not in ["LIGHT_SLEEP", "DEEP_SLEEP"]:
                report = self.generate_report()
                if mqtt_client:
                    try:
                        mqtt_client.publish(BODY_STATE_TOPIC + "/report", ujson.dumps(report))
                        print("睡眠报告已发送至MQTT")
                    except Exception as e:
                        print("发送睡眠报告失败:", e)
                self.print_sleep_summary()
                self.in_sleep_session = False
            if not self.in_sleep_session and new_stage in ["LIGHT_SLEEP", "DEEP_SLEEP"]:
                self.sleep_start_time = current_time
                self.light_sleep_duration = 0
                self.deep_sleep_duration = 0
                self.in_sleep_session = True

            self.last_stage = self.sleep_stage
            self.sleep_stage = new_stage
            print(f"状态变更: {self.last_stage} → {self.sleep_stage}")

        if self.in_sleep_session:
            if self.sleep_stage == "LIGHT_SLEEP":
                self.light_sleep_duration += Config.SAMPLING_PERIOD_MS / 1000
            elif self.sleep_stage == "DEEP_SLEEP":
                self.deep_sleep_duration += Config.SAMPLING_PERIOD_MS / 1000

        if sleep_detection_enabled:
            print(f"状态: {self.sleep_stage} | 压力: {avg_pressure:.0f} | 变异度: {variability:.1f}")

    def calculate_variability(self):
        variability = 0
        for i in range(3):
            mean = sum(self.buffer[i]) / Config.BUFFER_SIZE
            variance = sum((x - mean) ** 2 for x in self.buffer[i]) / Config.BUFFER_SIZE
            variability += math.sqrt(variance)
        return variability / 3

    def generate_report(self):
        report = {
            "device_id": "pillow-00001",
            "detection_start_time": self.detection_start_time,
            "detection_end_time": time.time(),
            "total_detection_seconds": int(time.time() - self.detection_start_time) if self.detection_start_time else 0,
            "final_sleep_stage": self.sleep_stage,
            "light_sleep_seconds": int(self.light_sleep_duration),
            "deep_sleep_seconds": int(self.deep_sleep_duration),
            "in_sleep_session": self.in_sleep_session,
            "timestamp": time.time()
        }

        if self.in_sleep_session and self.sleep_start_time:
            report["sleep_session_duration"] = int(time.time() - self.sleep_start_time)
            report["sleep_session_start"] = self.sleep_start_time

        self.print_sleep_summary()
        return report

    def print_sleep_summary(self):
        if self.sleep_start_time:
            duration = time.time() - self.sleep_start_time
            print("\n========== 💤 本次睡眠统计 ==========")
            print(f"总时长: {int(duration // 3600)}小时 {int((duration % 3600) // 60)}分钟 {int(duration % 60)}秒")
            print(
                f"浅睡时长: {int(self.light_sleep_duration // 3600)}小时 {int((self.light_sleep_duration % 3600) // 60)}分钟 {int(self.light_sleep_duration % 60)}秒")
            print(
                f"深睡时长: {int(self.deep_sleep_duration // 3600)}小时 {int((self.deep_sleep_duration % 3600) // 60)}分钟 {int(self.deep_sleep_duration % 60)}秒")
            print("====================================\n")

if __name__ == "__main__":
    print("6路气囊系统启动...")

    try:
        init_motors_safe()
        if connect_wifi():
            print("网络连接成功")
        else:
            print("网络连接失败，继续运行但部分功能受限")
    except Exception as e:
        print(f"初始化过程中出错: {e}")

    monitor = SleepMonitor()
    print("睡眠监测器初始化完成")

    timer = Timer(0)
    last_ping_time = time.time()

    def sampling_callback(t):
        try:
            monitor.update()
            check_play_duration()
            auto_reset_check()
        except Exception as e:
            print(f"定时器回调错误: {e}")

    try:
        timer.init(period=Config.SAMPLING_PERIOD_MS, mode=Timer.PERIODIC, callback=sampling_callback)
        print(f"定时器已启动，采样间隔: {Config.SAMPLING_PERIOD_MS}ms")

        while True:
            # 移除长延时，改为极短延时
            time.sleep_ms(10)  # 仅10毫秒延时，大幅提高MQTT响应速度

            # 处理MQTT消息
            if mqtt_client:
                try:
                    mqtt_client.check_msg()  # 高频检查MQTT消息
                except Exception as e:
                    print(f"MQTT消息处理错误: {e}")

            # 保活检查（每60秒一次）
            current_time = time.time()
            if current_time - last_ping_time > 60:
                try:
                    mqtt_client.ping()
                    print("MQTT 保活成功")
                except Exception as e:
                    print("MQTT ping失败，可能断开:", e)
                    # 尝试重连
                    try:
                        mqtt_client.connect()
                        mqtt_client.subscribe(SOUND_SYS_TOPIC)
                        mqtt_client.subscribe(BODY_STATE_TOPIC)
                        mqtt_client.subscribe(AIRBAG_TOPIC)
                        mqtt_client.subscribe(SOUND_DETECT_TOPIC)
                        print("MQTT重连成功")
                    except Exception as e2:
                        print("MQTT重连失败:", e2)
                last_ping_time = current_time

            # 处理UART命令
            if sound_system:
                try:
                    sound_system.process_uart_command()
                except AttributeError:
                    pass
                except Exception as e:
                    print(f"处理UART命令错误: {e}")

    except KeyboardInterrupt:
        print("程序被用户中断")
    except Exception as e:
        print(f"主循环错误: {e}")
    finally:
        print("正在安全关闭所有输出...")
        
        # 停止所有气泵
        for pwm in PUMP_EN_PINS:
            pwm.duty(0)
        
        # 关闭所有方向引脚
        for pin in PUMP_IN1_PINS + PUMP_IN2_PINS:
            pin.off()
        
        # 断开MQTT连接
        if mqtt_client:
            try:
                mqtt_client.disconnect()
                print("MQTT已断开连接")
            except:
                pass
        
        # 停止定时器
        try:
            timer.deinit()
            print("定时器已停止")
        except:
            pass
        
        print("6路气囊系统已安全停止")

