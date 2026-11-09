package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestReadyValidation rejects replay, ambiguous JSON, invalid ports and unbounded messages.
func TestReadyValidation(t *testing.T) {
	init, err := newControl(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	ready := readyMessage{Type: "ready", Version: 1, InstanceID: init.InstanceID, Challenge: init.Challenge, Port: 32123}
	valid, _ := json.Marshal(ready)
	valid = append(valid, '\n')
	if _, err := validateReady(valid, init); err != nil {
		t.Fatal(err)
	}
	for name, line := range map[string]string{
		"nonce":           strings.Replace(string(valid), init.Challenge, strings.Repeat("a", 64), 1),
		"instance":        strings.Replace(string(valid), init.InstanceID, strings.Repeat("b", 32), 1),
		"version":         strings.Replace(string(valid), `"version":1`, `"version":2`, 1),
		"zero-port":       strings.Replace(string(valid), `32123`, `0`, 1),
		"large-port":      strings.Replace(string(valid), `32123`, `65536`, 1),
		"fractional-port": strings.Replace(string(valid), `32123`, `3.5`, 1),
		"duplicate":       strings.Replace(string(valid), `"port":32123`, `"port":32123,"port":32123`, 1),
		"unknown":         strings.Replace(string(valid), `"port":32123`, `"port":32123,"exec":"evil"`, 1),
		"trailing":        string(valid) + "{}\n",
		"oversized":       strings.Repeat(" ", maxProtocolBytes) + string(valid),
		"incomplete":      strings.TrimSpace(string(valid)),
		"empty":           "\n",
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := validateReady([]byte(line), init); err == nil {
				t.Fatal("unsafe ready message was accepted")
			}
		})
	}
}

// TestOriginContainment rejects changed authorities, schemes and embedded credentials.
func TestOriginContainment(t *testing.T) {
	origin := "http://127.0.0.1:32123"
	for _, raw := range []string{origin, origin + "/", origin + "/?tab=private#section"} {
		if !sameOrigin(raw, origin) {
			t.Errorf("owned navigation denied: %s", raw)
		}
	}
	for _, raw := range []string{"https://127.0.0.1:32123", "http://localhost:32123", "http://127.0.0.1:8788",
		"http://127.0.0.1:32123.evil.invalid", "http://evil@127.0.0.1:32123", "file:///tmp/index.html", "javascript:alert(1)", "//127.0.0.1:32123", "http://[::1]:32123"} {
		if sameOrigin(raw, origin) {
			t.Errorf("unowned navigation accepted: %s", raw)
		}
	}
}

// helperCommand runs this native test executable with a synthetic child-only mode.
func helperCommand(mode string) *exec.Cmd {
	cmd := exec.Command(os.Args[0], "-test.run=^TestChildHelper$")
	cmd.Env = append(os.Environ(), "FLOWDESK_TEST_HELPER="+mode)
	cmd.Stderr = io.Discard
	return cmd
}

// TestChildHelper supplies real OS pipes and process handles without binding HTTP or importing providers.
func TestChildHelper(t *testing.T) {
	mode := os.Getenv("FLOWDESK_TEST_HELPER")
	if mode == "" {
		return
	}
	reader := bufio.NewReader(os.Stdin)
	var init controlMessage
	if json.NewDecoder(reader).Decode(&init) != nil {
		os.Exit(2)
	}
	if mode == "timeout" {
		time.Sleep(20 * time.Second)
		os.Exit(2)
	}
	ready := readyMessage{Type: "ready", Version: 1, InstanceID: init.InstanceID, Challenge: init.Challenge, Port: 32123}
	if mode == "nonce" {
		ready.Challenge = strings.Repeat("f", 64)
	}
	if mode == "oversized" {
		fmt.Print(strings.Repeat("x", maxProtocolBytes+1) + "\n")
	} else {
		json.NewEncoder(os.Stdout).Encode(ready)
	}
	if mode == "ignore-shutdown" {
		time.Sleep(20 * time.Second)
		os.Exit(2)
	}
	var shutdown controlMessage
	err := json.NewDecoder(reader).Decode(&shutdown)
	if err == io.EOF {
		os.Exit(0)
	}
	if err != nil || shutdown.Type != "shutdown" || shutdown.Challenge != init.Challenge || shutdown.InstanceID != init.InstanceID {
		os.Exit(2)
	}
	os.Exit(0)
}

// TestChildProtocolLifecycle exercises the exact launcher and idempotent shutdown against a native process.
func TestChildProtocolLifecycle(t *testing.T) {
	init, _ := newControl(t.TempDir())
	child, err := launchChild(context.Background(), helperCommand("normal"), init, 3*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { child.stop() })
	if child.origin() != "http://127.0.0.1:32123" {
		t.Fatal("invalid owned origin")
	}
	if err := child.stop(); err != nil {
		t.Fatal(err)
	}
	if err := child.stop(); err != nil || child.waitErr != nil {
		t.Fatalf("stop was not idempotent: %v, child: %v", err, child.waitErr)
	}
}

// TestChildEOF confirms the pipe lifetime independently terminates a cooperative child.
func TestChildEOF(t *testing.T) {
	init, _ := newControl(t.TempDir())
	child, err := launchChild(context.Background(), helperCommand("normal"), init, 3*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { child.stop() })
	child.stdin.Close()
	select {
	case <-child.done:
		if child.waitErr != nil {
			t.Fatal(child.waitErr)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("child survived EOF")
	}
}

// TestStartupFailureCleanup checks timeout and malformed readiness cannot leave a child behind.
func TestStartupFailureCleanup(t *testing.T) {
	for _, mode := range []string{"nonce", "oversized", "timeout"} {
		t.Run(mode, func(t *testing.T) {
			init, _ := newControl(t.TempDir())
			cmd := helperCommand(mode)
			child, err := launchChild(context.Background(), cmd, init, 300*time.Millisecond)
			if err == nil || child != nil || cmd.ProcessState == nil || !cmd.ProcessState.Exited() && cmd.ProcessState.Success() {
				t.Fatalf("startup failure did not reap owned child: %v", err)
			}
		})
	}
}

// TestOwnedProcessFallback keeps a separate native process alive while forcing one child's termination.
func TestOwnedProcessFallback(t *testing.T) {
	init, _ := newControl(t.TempDir())
	other, err := launchChild(context.Background(), helperCommand("normal"), init, 3*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { other.stop() })
	init, _ = newControl(t.TempDir())
	stubborn, err := launchChild(context.Background(), helperCommand("ignore-shutdown"), init, 3*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { stubborn.stop() })
	if err = stubborn.stop(); err != nil {
		t.Fatal(err)
	}
	select {
	case <-other.done:
		t.Fatal("fallback killed an unrelated owned test process")
	default:
	}
}

// TestPackagedPathAndEnvironment rejects relative resources and inherited deployment overrides.
func TestPackagedPathAndEnvironment(t *testing.T) {
	if _, err := sidecarExecutable("relative"); err == nil {
		t.Fatal("relative executable resource accepted")
	}
	if _, err := newControl("relative"); err == nil {
		t.Fatal("relative user directory accepted")
	}
	root := filepath.Join(t.TempDir(), "中文 app resources")
	executable := filepath.Join(root, "sidecar", "flowdesk-server", "flowdesk-server"+executableSuffix)
	if err := os.MkdirAll(filepath.Dir(executable), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(executable, nil, 0700); err != nil {
		t.Fatal(err)
	}
	if got, err := sidecarExecutable(root); err != nil || got != executable {
		t.Fatalf("packaged resource resolution failed: %v", err)
	}
	t.Setenv("FLOW_HOST", "0.0.0.0")
	t.Setenv("FLOW_TOKEN", "synthetic")
	t.Setenv("FLOWDESK_DATA_DIR", "relative")
	t.Setenv("PYTHONPATH", "synthetic")
	for _, entry := range childEnvironment() {
		if strings.HasPrefix(entry, "FLOW") || strings.HasPrefix(entry, "PYTHONPATH=") {
			t.Fatal("inherited deployment configuration was not removed")
		}
	}
}
