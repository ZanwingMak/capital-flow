package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// smokeRequest uses bounded HTTP and never follows a redirect outside the owned origin.
func smokeRequest(origin, method, path, requestOrigin string) (int, []byte, error) {
	client := &http.Client{Timeout: 4 * time.Second, Transport: &http.Transport{Proxy: nil},
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	defer client.CloseIdleConnections()
	var body io.Reader
	if method == "POST" {
		body = bytes.NewBufferString("{}")
	}
	request, err := http.NewRequest(method, origin+path, body)
	if err != nil {
		return 0, nil, err
	}
	if requestOrigin != "" {
		request.Header.Set("Origin", requestOrigin)
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := client.Do(request)
	if err != nil {
		return 0, nil, err
	}
	defer response.Body.Close()
	content, err := io.ReadAll(io.LimitReader(response.Body, 2<<20))
	return response.StatusCode, content, err
}

// smokePackaged exercises the real packaged executable with isolated synthetic data and no OpenD.
func smokePackaged(resources, userData string) error {
	child, logFile, err := startPackaged(context.Background(), resources, userData)
	if err != nil {
		return err
	}
	defer logFile.Close()
	defer child.stop()
	origin := child.origin()
	status, index, err := smokeRequest(origin, "GET", "/", "")
	if err != nil || status != 200 || !bytes.Contains(bytes.ToLower(index), []byte("<html")) {
		return fmt.Errorf("页面冒烟失败：HTTP %d %v", status, err)
	}
	// Read script and stylesheet references from the shipped page, including later indicator assets.
	assets := regexp.MustCompile(`(?:src|href)=["']([^"']+)["']`).FindAllSubmatch(index, -1)
	for _, asset := range assets {
		path := string(asset[1])
		if strings.Contains(path, ":") || strings.HasPrefix(path, "//") || strings.HasPrefix(path, "#") {
			continue
		}
		path = "/" + strings.TrimPrefix(path, "/")
		status, _, err = smokeRequest(origin, "GET", path, "")
		if err != nil || status != 200 {
			return fmt.Errorf("打包页面资源不可用：%s HTTP %d %v", path, status, err)
		}
	}
	status, health, err := smokeRequest(origin, "GET", "/api/health", "")
	var payload map[string]any
	if err != nil || status != 200 || json.Unmarshal(health, &payload) != nil || payload["serviceVersion"] == nil {
		return fmt.Errorf("健康接口冒烟失败：HTTP %d %v", status, err)
	}
	features, _ := payload["features"].([]any)
	foundIndicators := false
	for _, feature := range features {
		if feature == "indicators" {
			foundIndicators = true
		}
	}
	if !foundIndicators {
		return fmt.Errorf("打包健康状态缺少指标服务")
	}
	for _, check := range []struct {
		origin string
		status int
	}{{origin, 400}, {"https://evil.invalid", 403}} {
		status, _, err = smokeRequest(origin, "GET", "/api/indicators?unknown=synthetic", check.origin)
		if err != nil || status != check.status {
			return fmt.Errorf("指标入口验证失败：HTTP %d 预期 %d %v", status, check.status, err)
		}
	}
	for _, path := range []string{"/.env", "/server.py", "/unknown", "/data/portfolio.sqlite3", "/api/shutdown"} {
		status, _, err = smokeRequest(origin, "GET", path, "")
		if err != nil || status != 404 {
			return fmt.Errorf("未知资源未被拒绝：%s HTTP %d %v", path, status, err)
		}
	}
	for _, check := range []struct {
		path, origin string
		status       int
	}{
		{"/api/private/session", "", 403},
		{"/api/private/session", "https://evil.invalid", 403},
		{"/api/private/accounts", origin, 401},
		{"/api/private/accounts", "https://evil.invalid", 403},
		{"/api/private/session", origin, 200},
	} {
		status, _, err = smokeRequest(origin, "POST", check.path, check.origin)
		if err != nil || status != check.status {
			return fmt.Errorf("私有边界冒烟失败：HTTP %d 预期 %d %v", status, check.status, err)
		}
	}
	if _, err := os.Stat(filepath.Join(userData, "private")); !os.IsNotExist(err) {
		return fmt.Errorf("拒绝请求意外触及私有存储")
	}
	if err := child.stop(); err != nil {
		return err
	}
	if child.waitErr != nil {
		return fmt.Errorf("打包服务未正常退出：%w", child.waitErr)
	}
	connection, err := net.DialTimeout("tcp", strings.TrimPrefix(origin, "http://"), time.Second)
	if err == nil {
		connection.Close()
		return fmt.Errorf("退出后本实例端口仍被占用")
	}
	return nil
}
