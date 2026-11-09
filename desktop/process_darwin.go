//go:build darwin

package main

import (
	"os"
	"os/exec"
	"syscall"
)

const executableSuffix = ""

type processGuard struct{}

// prepareProcess creates a private process group for this application's sidecar.
func prepareProcess(cmd *exec.Cmd) (*processGuard, error) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	return &processGuard{}, nil
}

// attach needs no separate operation because macOS sets the group atomically at exec.
func (guard *processGuard) attach(process *os.Process) error { return nil }

// kill addresses only the group whose leader was launched by this host.
func (guard *processGuard) kill(process *os.Process) { syscall.Kill(-process.Pid, syscall.SIGKILL) }

// close has no kernel handle to release on macOS.
func (guard *processGuard) close() {}
