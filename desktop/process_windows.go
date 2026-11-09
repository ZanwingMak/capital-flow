//go:build windows

package main

import (
	"os"
	"os/exec"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

const executableSuffix = ".exe"

type processGuard struct{ job windows.Handle }

// prepareProcess configures an owned Job whose close kills only its assigned descendants.
func prepareProcess(cmd *exec.Cmd) (*processGuard, error) {
	job, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return nil, err
	}
	info := windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION{}
	info.BasicLimitInformation.LimitFlags = windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	_, err = windows.SetInformationJobObject(job, windows.JobObjectExtendedLimitInformation,
		uintptr(unsafe.Pointer(&info)), uint32(unsafe.Sizeof(info)))
	if err != nil {
		windows.CloseHandle(job)
		return nil, err
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NEW_PROCESS_GROUP}
	return &processGuard{job: job}, nil
}

// attach contains the child before it receives init, including PyInstaller descendants.
func (guard *processGuard) attach(process *os.Process) error {
	handle, err := windows.OpenProcess(windows.PROCESS_SET_QUOTA|windows.PROCESS_TERMINATE, false, uint32(process.Pid))
	if err != nil {
		return err
	}
	defer windows.CloseHandle(handle)
	return windows.AssignProcessToJobObject(guard.job, handle)
}

// kill terminates this application's Job without searching process names or ports.
func (guard *processGuard) kill(process *os.Process) { windows.TerminateJobObject(guard.job, 1) }

// close enforces kill-on-close and releases the non-inheritable Job handle.
func (guard *processGuard) close() { windows.CloseHandle(guard.job) }
