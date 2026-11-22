# Version 16

import requests
import argparse
import time
import logging
import sys
from threading import Thread, Lock, Event
from queue import Queue
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

# 本地任务队列
task_queue = Queue()

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

def save_successful_proxies(file_path, successful_proxies):
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
                    return full_proxy
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
                return proxy
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
    return None

def worker(random_ua, skip_invalid_proxy, daemon, interval, show_progress, total_proxies, total_urls, verbose):
    """本地队列工作函数"""
    successful_proxies = set()
    while not exit_event.is_set():
        try:
            url, proxy = task_queue.get(timeout=interval)
            successful_proxy = visit_website(url, proxy, random_ua, skip_invalid_proxy, show_progress, total_proxies, total_urls, verbose)
            if successful_proxy:
                successful_proxies.add(successful_proxy)
            task_queue.task_done()
        except Exception as e:
            if verbose:
                with output_lock:
                    logging.error(f"任务处理异常: {e}")
                    print(f"任务处理异常: {e}")
            break
        if not daemon:
            break
        time.sleep(interval)
    return successful_proxies

def main():
    global success_count, failure_count
    parser = argparse.ArgumentParser(description="访问指定网站的程序")  # 启用默认的 -h/--help
    parser.add_argument('--url-file', help="包含URL列表的.txt文件路径")
    parser.add_argument('--proxy-file', help="包含代理列表的.txt文件路径")
    parser.add_argument('--use-proxy', action='store_true', help="是否使用代理")
    parser.add_argument('--random-ua', action='store_true', help="随机生成User-Agent")
    parser.add_argument('--skip-invalid-proxy', action='store_true', help="跳过无效代理")
    parser.add_argument('--daemon', action='store_true', help="通霄挂机无人值守模式，程序会持续运行，直到手动停止")
    parser.add_argument('--interval', type=int, default=5, help="挂机模式下的间隔时间（秒），默认5秒")
    parser.add_argument('--threads', type=int, default=1, help="多线程访问，每个线程使用一个代理（默认1）")
    parser.add_argument('--stats', action='store_true', help="启用统计功能，显示成功和失败的次数")
    parser.add_argument('--progress', action='store_true', help="启用进度显示功能，显示当前代理和目标网址的进度")
    parser.add_argument('--verbose', action='store_true', help="启用详细输出，显示失败信息")
    parser.add_argument('--output-file', default="successful_proxies.txt", help="保存成功代理的文件路径，默认为 successful_proxies.txt")

    # 解析参数
    args = parser.parse_args()

    # 检查是否启用了必填参数
    if not args.url_file:
        parser.print_help()
        print("\n错误：必须提供 --url-file 参数！")
        return

    # 读取URL列表
    urls = read_urls_from_file(args.url_file)
    total_urls = len(urls)

    # 读取代理列表（如果启用代理）
    proxies = []
    if args.use_proxy and args.proxy_file:
        proxies = read_proxies_from_file(args.proxy_file)
    total_proxies = len(proxies)

    # 将任务推送到本地队列
    for url in urls:
        for proxy in proxies:
            task_queue.put((url, proxy))

    # 启动多线程
    threads = []
    successful_proxies = set()
    for i in range(args.threads):
        thread = Thread(
            target=worker,
            args=(args.random_ua, args.skip_invalid_proxy, args.daemon, args.interval, args.progress, total_proxies, total_urls, args.verbose),
        )
        thread.start()
        threads.append(thread)

    # 等待所有任务完成
    try:
        while not task_queue.empty():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n检测到用户中断，正在退出程序...")
        exit_event.set()

    # 等待所有线程完成
    for thread in threads:
        thread.join()

    # 如果启用了统计功能，输出统计结果
    if args.stats or args.progress:
        with output_lock:
            print(f"\n合计结果：成功 {success_count} 次，失败 {failure_count} 次")
            print(f"代理总数：{total_proxies}，目标网址总数：{total_urls}")

    # 保存成功的代理到文件
    save_successful_proxies(args.output_file, successful_proxies)

if __name__ == "__main__":
    main()
