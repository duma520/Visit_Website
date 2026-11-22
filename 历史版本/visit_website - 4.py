# Version 3.0.0 每次小更新 增加第三位数字，稍大的更新，增加第二位数字，大更新增加第一位数字

# Version 3.0.0

import requests
import argparse
import time
import logging
import sys
from threading import Thread, Lock
from fake_useragent import UserAgent

# 随机 User-Agent 生成器
ua = UserAgent()

# 配置日志
logging.basicConfig(
    level=logging.WARNING,  # 仅显示警告及以上级别的日志
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="visit_website.log",
)

# 全局锁，用于保护代理列表和统计信息
proxy_lock = Lock()
stats_lock = Lock()
output_lock = Lock()  # 用于保护输出

# 统计成功和失败的次数
success_count = 0
failure_count = 0

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

def try_proxy(url, proxy, headers, timeout=10):
    """尝试使用代理访问网站"""
    try:
        response = requests.get(url, headers=headers, proxies={"http": proxy, "https": proxy}, timeout=timeout)
        return response.status_code
    except requests.RequestException as e:
        return None

def visit_website(url, proxy, random_ua, skip_invalid_proxy, show_progress, total_proxies, total_urls, verbose):
    """访问指定网站"""
    global success_count, failure_count
    headers = {'User-Agent': ua.random} if random_ua else {}
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
                    return
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
                        logging.error(f"访问 {url} 失败，所有协议尝试均失败: {proxy}")
                        print(f"访问 {url} 失败，所有协议尝试均失败: {proxy}")
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
            response = requests.get(url, headers=headers, timeout=10)
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

def worker(urls, proxies, random_ua, skip_invalid_proxy, daemon, thread_id, interval, show_progress, total_proxies, total_urls, verbose):
    """多线程工作函数"""
    while True:
        # 遍历所有代理
        for proxy in proxies:
            # 使用当前代理访问所有 URL
            for url in urls:
                visit_website(url, proxy, random_ua, skip_invalid_proxy, show_progress, total_proxies, total_urls, verbose)

        if not daemon:
            break
        time.sleep(interval)  # 挂机模式下，按指定间隔时间访问

def main():
    global success_count, failure_count
    parser = argparse.ArgumentParser(description="访问指定网站的程序", add_help=False)  # 禁用默认的 -h/--help
    parser.add_argument('--help-cn', action='store_true', help="显示中文帮助信息")  # 自定义中文帮助参数
    parser.add_argument('--url-file', help="包含URL列表的.txt文件路径")
    parser.add_argument('--proxy-file', help="包含代理列表的.txt文件路径")
    parser.add_argument('--use-proxy', action='store_true', help="是否使用代理")
    parser.add_argument('--random-ua', action='store_true', help="随机生成User-Agent")
    parser.add_argument('--skip-invalid-proxy', action='store_true', help="跳过无效代理")
    parser.add_argument('--daemon', action='store_true', help="通宵挂机无人值守模式")
    parser.add_argument('--restart', action='store_true', help="通宵挂机无人值守，程序运行完毕后重新运行")
    parser.add_argument('--interval', type=int, default=5, help="挂机模式下的间隔时间（秒），默认5秒")
    parser.add_argument('--threads', type=int, default=1, help="多线程访问，每个线程使用一个代理（默认1）")
    parser.add_argument('--stats', action='store_true', help="启用统计功能，显示成功和失败的次数")
    parser.add_argument('--progress', action='store_true', help="启用进度显示功能，显示当前代理和目标网址的进度")
    parser.add_argument('--verbose', action='store_true', help="启用详细输出，显示失败信息")

    # 解析参数
    args = parser.parse_args()

    # 显示中文帮助信息
    if args.help_cn:
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
            --help-cn         显示中文帮助信息
        """)
        return

    # 如果未提供 --url-file 参数，显示帮助信息并退出
    if not args.url_file:
        parser.print_help()
        return

    # 读取URL列表
    urls = read_urls_from_file(args.url_file)
    total_urls = len(urls)

    # 读取代理列表（如果启用代理）
    proxies = []
    if args.use_proxy and args.proxy_file:
        proxies = read_proxies_from_file(args.proxy_file)
    total_proxies = len(proxies)

    # 启动多线程
    threads = []
    try:
        while True:
            for i in range(args.threads):
                thread = Thread(
                    target=worker,
                    args=(urls, proxies, args.random_ua, args.skip_invalid_proxy, args.daemon, i, args.interval, args.progress, total_proxies, total_urls, args.verbose)
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
        # 如果启用了统计功能，输出统计结果
        if args.stats or args.progress:
            with output_lock:
                print(f"\n合计结果：成功 {success_count} 次，失败 {failure_count} 次")
                print(f"代理总数：{total_proxies}，目标网址总数：{total_urls}")
        # 确保所有线程退出
        for thread in threads:
            thread.join()
        sys.exit(0)

if __name__ == "__main__":
    main()
