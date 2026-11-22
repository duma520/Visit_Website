# Version 13

import requests
import argparse
import time
import logging
import sys
import redis
from threading import Thread, Lock, Event
from fake_useragent import UserAgent
from fake_headers import Headers

# 随机 User-Agent 和请求头生成器
ua = UserAgent()
headers_gen = Headers(headers=True)  # 生成完整的请求头

# 配置日志
logging.basicConfig(
    level=logging.WARNING,  # 仅显示警告及以上级别的日志
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="visit_website.log",
)

# 全局锁，用于保护统计信息
stats_lock = Lock()
output_lock = Lock()  # 用于保护输出

# 统计成功和失败的次数
success_count = 0
failure_count = 0

# 退出标志
exit_event = Event()

# Redis 连接
r = redis.Redis(host='localhost', port=6379, db=0)

def read_urls_from_file(file_path):
    """从文件中读取URL列表"""
    with open(file_path, 'r') as file:
        urls = file.read().splitlines()
    return urls

def read_proxies_from_file(file_path):
    """从文件中读取代理列表"""
    with open(file_path, 'r') as file:
        proxies = file.read().splitlines()
    return proxies

def save_successful_proxies(file_path):
    """将成功的代理保存到文件（追加模式）"""
    with open(file_path, 'a') as file:  # 使用 'a' 模式追加内容
        for proxy in successful_proxies:
            file.write(proxy + '\n')

def try_proxy(url, proxy, headers, timeout=5):
    """尝试使用代理访问网站"""
    try:
        response = requests.get(url, headers=headers, proxies={"http": proxy, "https": proxy}, timeout=timeout)
        return response.status_code
    except requests.RequestException as e:
        return None

def visit_website(url, proxy, random_ua, skip_invalid_proxy, show_progress, total_proxies, total_urls, verbose):
    """访问指定网站"""
    global success_count, failure_count
    headers = headers_gen.generate() if random_ua else {}  # 使用 fake-headers 生成随机请求头
    if proxy:
        # 如果代理没有前缀，尝试三种协议
        if not proxy.startswith(('http://', 'https://', 'socks5://')):
            protocols = ['http://', 'https://', 'socks5://']
            for protocol in protocols:
                full_proxy = f"{protocol}{proxy}"
                status_code = try_proxy(url, full_proxy, headers)
                if status_code:
                    with stats_lock:
                        success_count += 1
                    logging.info(f"访问 {url} 成功，状态码: {status_code}，使用的代理: {full_proxy}")
                    if show_progress:
                        with output_lock:
                            print(f"\r进度：代理总数 {total_proxies}，目标网址总数 {total_urls}，当前代理 {proxy}，目标网址 {url}，成功 {success_count}，失败 {failure_count}", end="", flush=True)
                    # 记录成功的代理
                    r.sadd("successful_proxies", full_proxy)
                    return
                else:
                    with stats_lock:
                        failure_count += 1
                    if skip_invalid_proxy:
                        if verbose:
                            with output_lock:
                                logging.warning(f"访问 {url} 失败，跳过无效代理: {full_proxy}")
                                print(f"访问 {url} 失败，跳过无效代理: {full_proxy}")
                    else:
                        if verbose:
                            with output_lock:
                                logging.error(f"访问 {url} 失败，错误: {full_proxy}")
                                print(f"访问 {url} 失败，错误: {full_proxy}")
        else:
            # 如果代理有前缀，直接使用
            status_code = try_proxy(url, proxy, headers)
            if status_code:
                with stats_lock:
                    success_count += 1
                logging.info(f"访问 {url} 成功，状态码: {status_code}，使用的代理: {proxy}")
                if show_progress:
                    with output_lock:
                        print(f"\r进度：代理总数 {total_proxies}，目标网址总数 {total_urls}，当前代理 {proxy}，目标网址 {url}，成功 {success_count}，失败 {failure_count}", end="", flush=True)
                # 记录成功的代理
                r.sadd("successful_proxies", proxy)
            else:
                with stats_lock:
                    failure_count += 1
                if skip_invalid_proxy:
                    if verbose:
                        with output_lock:
                            logging.warning(f"访问 {url} 失败，跳过无效代理: {proxy}")
                            print(f"访问 {url} 失败，跳过无效代理: {proxy}")
                else:
                    if verbose:
                        with output_lock:
                            logging.error(f"访问 {url} 失败，错误: {proxy}")
                            print(f"访问 {url} 失败，错误: {proxy}")
    else:
        # 不使用代理
        try:
            response = requests.get(url, headers=headers, timeout=5)
            with stats_lock:
                success_count += 1
            logging.info(f"访问 {url} 成功，状态码: {response.status_code}")
            if show_progress:
                with output_lock:
                    print(f"\r进度：代理总数 {total_proxies}，目标网址总数 {total_urls}，当前代理 无，目标网址 {url}，成功 {success_count}，失败 {failure_count}", end="", flush=True)
        except requests.RequestException as e:
            with stats_lock:
                failure_count += 1
            logging.error(f"访问 {url} 失败，错误: {e}")
            if verbose:
                with output_lock:
                    print(f"访问 {url} 失败，错误: {e}")

def worker(random_ua, skip_invalid_proxy, daemon, thread_id, interval, show_progress, total_proxies, total_urls, verbose):
    """分布式爬虫工作函数"""
    while not exit_event.is_set():
        # 从 Redis 队列中获取任务
        task = r.blpop("tasks", timeout=interval)
        if task:
            url, proxy = task[1].decode().split('|')
            visit_website(url, proxy, random_ua, skip_invalid_proxy, show_progress, total_proxies, total_urls, verbose)
        elif not daemon:
            break

def main():
    global success_count, failure_count
    parser = argparse.ArgumentParser(description="访问指定网站的程序")  # 启用默认的 -h/--help
    parser.add_argument('--url-file', help="包含URL列表的.txt文件路径")
    parser.add_argument('--proxy-file', help="包含代理列表的.txt文件路径")
    parser.add_argument('--use-proxy', action='store_true', help="是否使用代理")
    parser.add_argument('--random-ua', action='store_true', help="随机生成User-Agent")
    parser.add_argument('--skip-invalid-proxy', action='store_true', help="跳过无效代理")
    parser.add_argument('--daemon', action='store_true', help="通宵挂机无人值守模式，启用守护进程模式（即挂机模式），程序会持续运行，直到手动停止")
    parser.add_argument('--restart', action='store_true', help="启用重启模式（非持续挂机），程序在完成一轮任务后会重新启动，继续执行下一轮任务")
    parser.add_argument('--interval', type=int, default=5, help="挂机模式下的间隔时间（秒），默认5秒")
    parser.add_argument('--threads', type=int, default=1, help="多线程访问，每个线程使用一个代理（默认1）")
    parser.add_argument('--stats', action='store_true', help="启用统计功能，显示成功和失败的次数")
    parser.add_argument('--progress', action='store_true', help="启用进度显示功能，显示当前代理和目标网址的进度")
    parser.add_argument('--verbose', action='store_true', help="启用详细输出，显示失败信息")
    parser.add_argument('--output-file', default="successful_proxies.txt", help="保存成功代理的文件路径，默认为 successful_proxies.txt")

    # 解析参数
    args = parser.parse_args()

    # 检查是否同时启用了 --daemon 和 --restart
    if args.daemon and args.restart:
        print("错误：不能同时启用 --daemon 和 --restart 模式")
        sys.exit(1)

    # 如果未提供 --url-file 参数，显示帮助信息并退出
    if not args.url_file:
        parser.print_help()
        print("\n中文帮助信息：")
        print("""
        访问指定网站的程序
        用法:
            python script.py --url-file urls.txt [可选参数]
        可选参数:
            --url-file        包含URL列表的.txt文件路径（必需）
            --proxy-file      包含代理列表的.txt文件路径（可选）
            --use-proxy       是否使用代理（可选）
            --random-ua       随机生成User-Agent（可选）
            --skip-invalid-proxy 跳过无效代理（可选）
            --daemon          通宵挂机无人值守模式（可选）
            --restart         通宵挂机无人值守，程序运行完毕后重新运行（可选）
            --interval        挂机模式下的间隔时间（秒），默认5秒（可选）
            --threads         多线程访问，每个线程使用一个代理（默认1）
            --stats           启用统计功能，显示成功和失败的次数（可选）
            --progress        启用进度显示功能，显示当前代理和目标网址的进度（可选）
            --verbose         启用详细输出，显示失败信息（可选）
            --output-file     保存成功代理的文件路径，默认为 successful_proxies.txt
        """)
        return

    # 读取URL列表
    urls = read_urls_from_file(args.url_file)
    total_urls = len(urls)

    # 读取代理列表（如果启用代理）
    proxies = []
    if args.use_proxy and args.proxy_file:
        proxies = read_proxies_from_file(args.proxy_file)
    total_proxies = len(proxies)

    # 将任务推送到 Redis 队列
    for url in urls:
        for proxy in proxies:
            r.rpush("tasks", f"{url}|{proxy}")

    # 启动多线程
    threads = []
    try:
        while True:
            for i in range(args.threads):
                thread = Thread(
                    target=worker,
                    args=(args.random_ua, args.skip_invalid_proxy, args.daemon, i, args.interval, args.progress, total_proxies, total_urls, args.verbose),
                    daemon=True  # 设置为守护线程
                )
                thread.start()
                threads.append(thread)

            # 等待所有线程完成
            for thread in threads:
                thread.join()

            # 如果启用了统计功能，输出统计结果
            if args.stats or args.progress:
                with output_lock:
                    print(f"\n合计结果：成功 {success_count} 次，失败 {failure_count} 次")
                    print(f"代理总数：{total_proxies}，目标网址总数：{total_urls}")

            # 如果不启用重启模式，退出循环
            if not args.restart:
                break
    except KeyboardInterrupt:
        print("\n检测到用户中断，正在退出程序...")
        exit_event.set()  # 设置退出标志
        # 如果启用了统计功能，输出统计结果
        if args.stats or args.progress:
            with output_lock:
                print(f"\n合计结果：成功 {success_count} 次，失败 {failure_count} 次")
                print(f"代理总数：{total_proxies}，目标网址总数：{total_urls}")
        # 确保所有线程退出
        for thread in threads:
            thread.join()
        # 保存成功的代理到文件
        successful_proxies = r.smembers("successful_proxies")
        with open(args.output_file, 'a') as file:
            for proxy in successful_proxies:
                file.write(proxy.decode() + '\n')
        sys.exit(0)

if __name__ == "__main__":
    main()
