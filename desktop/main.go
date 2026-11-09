package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"html"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"

	"github.com/egoist/mygo"
)

// startPackaged launches only the runtime beside this installed host and owns its log file.
func startPackaged(ctx context.Context, resources, userData string) (*childProcess, io.Closer, error) {
	path, err := sidecarExecutable(resources)
	if err != nil {
		return nil, nil, err
	}
	init, err := newControl(userData)
	if err != nil {
		return nil, nil, err
	}
	if err = os.MkdirAll(filepath.Join(userData, "logs"), 0700); err != nil {
		return nil, nil, err
	}
	logFile, err := os.OpenFile(filepath.Join(userData, "logs", "desktop.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return nil, nil, err
	}
	cmd := exec.Command(path)
	cmd.Dir, cmd.Env, cmd.Stderr = userData, childEnvironment(), logFile
	child, err := launchChild(ctx, cmd, init, 30*time.Second)
	if err != nil {
		logFile.Close()
		return nil, nil, err
	}
	return child, logFile, nil
}

// statusHTML renders an inert loading or error view inside the native window.
func statusHTML(title, message, logPath string) string {
	return `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">` +
		`<style>body{background:#10141e;color:#e9edf7;font:16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:12vh 10vw;line-height:1.8}h1{font-size:28px}p{max-width:760px}code{overflow-wrap:anywhere;color:#a9c7ff}</style>` +
		`<h1>` + html.EscapeString(title) + `</h1><p>` + html.EscapeString(message) + `</p><p>本机日志：<code>` + html.EscapeString(logPath) + `</code></p>`
}

// restrictPage disables native permissions and window creation, and contains all page navigations.
func restrictPage(window *mygo.Window, origin string) {
	window.Page().SetPermissionHandler(func(mygo.PermissionRequest) bool { return false })
	window.Page().SetWindowOpenHandler(func(mygo.WindowOpenRequest) *mygo.WindowOptions { return nil })
	window.Page().OnWillNavigate(func(event *mygo.NavigateEvent) {
		if !sameOrigin(event.URL, origin) {
			event.PreventDefault()
		}
	})
}

// runDesktop holds the single-instance lock and keeps startup and shutdown off the UI thread.
func runDesktop(resources, userData string) error {
	if !mygo.App.RequestSingleInstanceLock() {
		return nil
	}
	ctx, cancel := context.WithCancel(context.Background())
	var workers sync.WaitGroup
	var window *mygo.Window
	logPath := filepath.Join(userData, "logs", "desktop.log")
	mygo.App.OnSecondInstance(func(args []string, workingDir string) {
		if window != nil && !window.IsDestroyed() {
			window.Restore()
			window.Focus()
		}
	})
	mygo.App.OnBeforeQuit(func(*mygo.QuitEvent) { cancel() })
	mygo.App.OnWindowAllClosed(func() { mygo.App.Quit() })
	mygo.App.WhenReady(func() {
		window = mygo.NewWindow(mygo.WindowOptions{Title: "Flowdesk", Width: 1320, Height: 880,
			MinWidth: 960, MinHeight: 640, Page: mygo.PageOptions{Untrusted: true}})
		restrictPage(window, "")
		window.Page().LoadHTML(statusHTML("正在启动 Flowdesk", "正在准备本机行情与研究服务，首次启动可能需要几秒。", logPath), "")
		workers.Add(1)
		go func() {
			defer workers.Done()
			child, logFile, err := startPackaged(ctx, resources, userData)
			if err != nil {
				mygo.App.WhenReady(func() {
					if ctx.Err() == nil && !window.IsDestroyed() {
						window.Page().LoadHTML(statusHTML("Flowdesk 无法启动", err.Error()+"。请重新安装完整应用，或检查用户目录的写入权限后重试。", logPath), "")
					}
				})
				return
			}
			defer logFile.Close()
			defer child.stop()
			mygo.App.WhenReady(func() {
				if ctx.Err() != nil || window.IsDestroyed() {
					return
				}
				loading := window
				window = mygo.NewWindow(mygo.WindowOptions{Title: "Flowdesk", URL: child.origin(),
					Width: 1320, Height: 880, MinWidth: 960, MinHeight: 640,
					Page: mygo.PageOptions{Untrusted: true}})
				restrictPage(window, child.origin())
				loading.Destroy()
			})
			select {
			case <-ctx.Done():
			case <-child.done:
				mygo.App.WhenReady(func() {
					if ctx.Err() == nil && !window.IsDestroyed() {
						window.Page().LoadHTML(statusHTML("本机服务已停止", "请退出并重新打开 Flowdesk。若仍不能恢复，请查看日志并重新安装完整应用。", logPath), "")
					}
				})
			}
		}()
	})
	err := mygo.App.Run()
	cancel()
	// The worker's stop has a bounded graceful wait and owned-process fallback.
	workers.Wait()
	return err
}

// main exposes a headless packaged smoke mode without starting a GUI or touching default private data.
func main() {
	smoke := flag.Bool("smoke-test", false, "验证已打包的本机服务后退出")
	headless := flag.Bool("headless", false, "与 --smoke-test 相同，无需图形会话")
	data := flag.String("data-dir", "", "冒烟测试专用的绝对合成用户目录")
	flag.Parse()
	mygo.App.SetName("Flowdesk")
	resources, err := mygo.App.Path(mygo.PathResources)
	if err == nil {
		var userData string
		if *smoke || *headless {
			if !filepath.IsAbs(*data) {
				err = fmt.Errorf("--smoke-test 必须提供绝对的 --data-dir 合成目录")
			} else {
				err = smokePackaged(resources, filepath.Clean(*data))
			}
		} else {
			userData, err = mygo.App.Path(mygo.PathUserData)
			if err == nil {
				err = runDesktop(resources, userData)
			}
		}
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "Flowdesk:", err)
		os.Exit(1)
	}
	if *smoke || *headless {
		json.NewEncoder(os.Stdout).Encode(map[string]any{"ok": true, "protocolVersion": protocolVersion, "checks": []string{"packaged-runtime", "challenge", "assets", "indicators", "private-boundary", "shutdown", "port-released"}})
	}
}
