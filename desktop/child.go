package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const protocolVersion = 1
const maxProtocolBytes = 16384

type controlMessage struct {
	Type       string `json:"type"`
	Version    int    `json:"version"`
	InstanceID string `json:"instanceId"`
	Challenge  string `json:"challenge"`
	UserData   string `json:"userData,omitempty"`
}

type readyMessage struct {
	Type       string `json:"type"`
	Version    int    `json:"version"`
	InstanceID string `json:"instanceId"`
	Challenge  string `json:"challenge"`
	Port       int    `json:"port"`
}

type childProcess struct {
	cmd      *exec.Cmd
	stdin    io.WriteCloser
	stdout   io.ReadCloser
	guard    *processGuard
	init     controlMessage
	ready    readyMessage
	done     chan struct{}
	waitErr  error
	stopOnce sync.Once
	stopErr  error
}

// randomHex creates a cryptographically random identifier for one child only.
func randomHex(size int) (string, error) {
	value := make([]byte, size)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return hex.EncodeToString(value), nil
}

// newControl creates the challenge and instance identity without using a port probe.
func newControl(userData string) (controlMessage, error) {
	if !filepath.IsAbs(userData) {
		return controlMessage{}, errors.New("用户数据目录必须是绝对目录")
	}
	challenge, err := randomHex(32)
	if err != nil {
		return controlMessage{}, err
	}
	instance, err := randomHex(16)
	return controlMessage{Type: "init", Version: protocolVersion, InstanceID: instance, Challenge: challenge, UserData: userData}, err
}

// sidecarExecutable resolves only the fixed, absolute packaged resource executable.
func sidecarExecutable(resources string) (string, error) {
	if !filepath.IsAbs(resources) {
		return "", errors.New("应用资源目录必须是绝对目录")
	}
	name := "flowdesk-server" + executableSuffix
	path := filepath.Join(resources, "sidecar", "flowdesk-server", name)
	info, err := os.Stat(path)
	if err != nil || !info.Mode().IsRegular() {
		return "", fmt.Errorf("桌面运行时缺失，请重新安装完整的 Flowdesk 应用：%s", path)
	}
	return path, nil
}

// childEnvironment excludes inherited web deployment flags and Python injection paths.
func childEnvironment() []string {
	environment := []string{"PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1", "PYINSTALLER_RESET_ENVIRONMENT=1"}
	for _, entry := range os.Environ() {
		name, _, _ := strings.Cut(entry, "=")
		upper := strings.ToUpper(name)
		if strings.HasPrefix(upper, "FLOW") || strings.HasPrefix(upper, "PYTHON") || strings.HasPrefix(upper, "PYINSTALLER_") {
			continue
		}
		environment = append(environment, entry)
	}
	return environment
}

// launchChild owns one OS process group or Windows Job and returns only after verified readiness.
func launchChild(ctx context.Context, cmd *exec.Cmd, init controlMessage, timeout time.Duration) (*childProcess, error) {
	child := &childProcess{cmd: cmd, init: init, done: make(chan struct{})}
	var err error
	child.stdin, err = cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	child.stdout, err = cmd.StdoutPipe()
	if err != nil {
		child.stdin.Close()
		return nil, err
	}
	child.guard, err = prepareProcess(cmd)
	if err != nil {
		child.stdin.Close()
		child.stdout.Close()
		return nil, err
	}
	if err = cmd.Start(); err != nil {
		child.stdin.Close()
		child.stdout.Close()
		child.guard.close()
		return nil, err
	}
	// Attach before sending init; an uncontained Windows child never starts HTTP.
	if err = child.guard.attach(cmd.Process); err != nil {
		cmd.Process.Kill()
		cmd.Wait()
		child.stdin.Close()
		child.stdout.Close()
		child.guard.close()
		return nil, err
	}
	go func() {
		child.waitErr = cmd.Wait()
		close(child.done)
	}()
	if err = json.NewEncoder(child.stdin).Encode(init); err != nil {
		child.stop()
		return nil, err
	}
	result := make(chan error, 1)
	go func() {
		reader := bufio.NewReaderSize(child.stdout, maxProtocolBytes)
		line, readErr := reader.ReadSlice('\n')
		if readErr == nil {
			child.ready, readErr = validateReady(line, init)
		}
		result <- readErr
	}()
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case err = <-result:
	case <-ctx.Done():
		err = ctx.Err()
	case <-timer.C:
		err = errors.New("桌面服务启动超时，请检查本机运行时和日志")
	}
	if err != nil {
		child.stop()
		return nil, fmt.Errorf("桌面服务未能就绪：%w", err)
	}
	return child, nil
}

// validateReady strictly checks the bounded reply against this host's random challenge.
func validateReady(line []byte, init controlMessage) (readyMessage, error) {
	var ready readyMessage
	if len(line) > maxProtocolBytes || !bytes.HasSuffix(line, []byte{'\n'}) {
		return ready, errors.New("就绪报文过长或不完整")
	}
	// Re-encode a map to reject duplicate keys in the wire representation.
	decoder := json.NewDecoder(bytes.NewReader(line))
	if token, err := decoder.Token(); err != nil || token != json.Delim('{') {
		return ready, errors.New("就绪报文不是JSON对象")
	}
	fields := map[string]json.RawMessage{}
	for decoder.More() {
		token, err := decoder.Token()
		if err != nil {
			return ready, err
		}
		key, ok := token.(string)
		if !ok || fields[key] != nil {
			return ready, errors.New("就绪报文含重复字段")
		}
		var value json.RawMessage
		if err = decoder.Decode(&value); err != nil {
			return ready, err
		}
		fields[key] = value
	}
	if _, err := decoder.Token(); err != nil {
		return ready, err
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return ready, errors.New("就绪报文含额外内容")
	}
	if len(fields) != 5 {
		return ready, errors.New("就绪报文字段无效")
	}
	strict := json.NewDecoder(bytes.NewReader(line))
	strict.DisallowUnknownFields()
	if err := strict.Decode(&ready); err != nil {
		return ready, err
	}
	if ready.Type != "ready" || ready.Version != protocolVersion || ready.Port < 1 || ready.Port > 65535 ||
		subtle.ConstantTimeCompare([]byte(ready.Challenge), []byte(init.Challenge)) != 1 ||
		subtle.ConstantTimeCompare([]byte(ready.InstanceID), []byte(init.InstanceID)) != 1 {
		return ready, errors.New("就绪报文的版本、端口或挑战码不匹配")
	}
	return ready, nil
}

// origin returns the literal loopback origin of the child this host created.
func (child *childProcess) origin() string {
	return fmt.Sprintf("http://127.0.0.1:%d", child.ready.Port)
}

// sameOrigin permits navigation only to this exact scheme and authority, without credentials.
func sameOrigin(raw, origin string) bool {
	value, err := url.Parse(raw)
	if err != nil || value.User != nil || value.Opaque != "" {
		return false
	}
	expected, err := url.Parse(origin)
	return err == nil && value.Scheme == "http" && value.Scheme == expected.Scheme && value.Host == expected.Host
}

// stop gracefully closes the owned child, then bounds fallback termination to its own group or Job.
func (child *childProcess) stop() error {
	child.stopOnce.Do(func() {
		message := child.init
		message.Type, message.UserData = "shutdown", ""
		// Only one short control message is written after init, so the pipe cannot fill.
		json.NewEncoder(child.stdin).Encode(message)
		child.stdin.Close()
		select {
		case <-child.done:
		case <-time.After(4 * time.Second):
			child.guard.kill(child.cmd.Process)
			select {
			case <-child.done:
			case <-time.After(2 * time.Second):
				child.stopErr = errors.New("桌面服务退出超时")
			}
		}
		child.guard.close()
		child.stdout.Close()
	})
	return child.stopErr
}
