from HTTP import HTTP_Server
import cProfile


def main():
    server = HTTP_Server("localhost", 8080)
    server.set_web_root("C:\\Users\derek\\Desktop\\web-root")
    server.run()


if __name__ == "__main__":
    # run main, don't save results in a file, sort by column 2 (cumtime)
    #cProfile.run('main()', None, 2)
    profiler = cProfile.Profile()
    try:
        profiler.run('main()')
    except KeyboardInterrupt:
        profiler.print_stats(2)  # Sort by cumulative time
        quit()