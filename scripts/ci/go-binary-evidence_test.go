package main

import (
	"bytes"
	"crypto/sha256"
	"debug/elf"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime/debug"
	"sort"
	"strings"
	"testing"
)

func TestSupportedGoVersions(t *testing.T) {
	for _, version := range []string{"go1.18", "go1.18.10", "go1.26.8", "go1.27.2", "go1.26.8-X:nodwarf5"} {
		if !supportedVersion(version) {
			t.Errorf("released version %q rejected", version)
		}
	}
	for _, version := range []string{"", "go1.17.13", "go1.28.0", "go2.0.0", "go1.27rc1", "devel go1.27", "go1.27.2 customized", "go1.26rc2-X:nodwarf5", "go1.25.1-X:nodwarf5", "go1.26.8-X:nodwarf5,unknown", "go1.26.8-X:unknown"} {
		if supportedVersion(version) {
			t.Errorf("unreviewed version %q accepted", version)
		}
	}
}

func TestUnusedGo126TextWord(t *testing.T) {
	data, text := pclnFixture()
	binary.LittleEndian.PutUint64(data[24:], 0)
	_, start, err := validatePCLN(data, text)
	if err != nil || start != 0 {
		t.Fatalf("Go 1.26 unused header word treated as corrupt: start=%x err=%v", start, err)
	}
	settings := map[string]string{"CGO_ENABLED": "0", "-compiler": "gc", "-buildmode": "exe"}
	address, source, err := resolveTextAddress(start, "go1.26.8-X:nodwarf5", settings, text)
	if err != nil || address != text.Addr || source != "elf-text-section-relative-cgo-disabled" {
		t.Fatalf("reviewed Go 1.26 section-relative provenance missing: address=%x source=%q err=%v", address, source, err)
	}
	settings["CGO_ENABLED"] = "1"
	if _, _, err := resolveTextAddress(start, "go1.26.8", settings, text); err == nil {
		t.Fatal("cgo runtime.text guessed from section address")
	}
	settings["CGO_ENABLED"] = "0"
	if _, _, err := resolveTextAddress(start, "go1.25.8", settings, text); err == nil {
		t.Fatal("older unused/unrelocated runtime.text silently accepted")
	}
}

func pclnFixture() ([]byte, *elf.Section) {
	data := make([]byte, 256)
	binary.LittleEndian.PutUint32(data, 0xfffffff1)
	data[6], data[7] = 1, 8
	values := []uint64{1, 1, 0x1000, 72, 80, 88, 96, 104}
	for i, value := range values {
		binary.LittleEndian.PutUint64(data[8+i*8:], value)
	}
	text := &elf.Section{SectionHeader: elf.SectionHeader{Addr: 0x1000, Size: 0x1000, Flags: elf.SHF_EXECINSTR}}
	return data, text
}

func TestPCLNRejectsMalformedMetadata(t *testing.T) {
	valid, text := pclnFixture()
	if count, start, err := validatePCLN(valid, text); err != nil || count != 1 || start != 0x1000 {
		t.Fatalf("valid control rejected: count=%d start=%x error=%v", count, start, err)
	}
	tests := []struct {
		name   string
		mutate func([]byte, *elf.Section) ([]byte, *elf.Section)
	}{
		{"short", func(d []byte, s *elf.Section) ([]byte, *elf.Section) { return d[:71], s }},
		{"magic", func(d []byte, s *elf.Section) ([]byte, *elf.Section) { d[0] = 0; return d, s }},
		{"pointer width", func(d []byte, s *elf.Section) ([]byte, *elf.Section) { d[7] = 4; return d, s }},
		{"zero functions", func(d []byte, s *elf.Section) ([]byte, *elf.Section) {
			binary.LittleEndian.PutUint64(d[8:], 0)
			return d, s
		}},
		{"allocation count", func(d []byte, s *elf.Section) ([]byte, *elf.Section) {
			binary.LittleEndian.PutUint64(d[8:], ^uint64(0))
			return d, s
		}},
		{"file allocation count", func(d []byte, s *elf.Section) ([]byte, *elf.Section) {
			binary.LittleEndian.PutUint64(d[16:], ^uint64(0))
			return d, s
		}},
		{"offset before header", func(d []byte, s *elf.Section) ([]byte, *elf.Section) {
			binary.LittleEndian.PutUint64(d[32:], 8)
			return d, s
		}},
		{"offset beyond section", func(d []byte, s *elf.Section) ([]byte, *elf.Section) {
			binary.LittleEndian.PutUint64(d[64:], uint64(len(d)))
			return d, s
		}},
		{"truncated function table", func(d []byte, s *elf.Section) ([]byte, *elf.Section) {
			binary.LittleEndian.PutUint64(d[64:], uint64(len(d)-4))
			return d, s
		}},
		{"text outside executable section", func(d []byte, s *elf.Section) ([]byte, *elf.Section) {
			binary.LittleEndian.PutUint64(d[24:], 0x3000)
			return d, s
		}},
		{"text overflow", func(d []byte, s *elf.Section) ([]byte, *elf.Section) { s.Size = ^uint64(0); return d, s }},
		{"text missing", func(d []byte, s *elf.Section) ([]byte, *elf.Section) { return d, nil }},
		{"nonexecutable text", func(d []byte, s *elf.Section) ([]byte, *elf.Section) { s.Flags = 0; return d, s }},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			data, section := pclnFixture()
			data, section = test.mutate(data, section)
			if _, _, err := validatePCLN(data, section); err == nil {
				t.Fatal("malformed metadata accepted")
			}
		})
	}
}

func elfHeaderFixture() []byte {
	data := make([]byte, 256)
	copy(data, []byte{0x7f, 'E', 'L', 'F', 2, 1})
	binary.LittleEndian.PutUint64(data[40:], 64)
	binary.LittleEndian.PutUint16(data[58:], 64)
	binary.LittleEndian.PutUint16(data[60:], 2)
	binary.LittleEndian.PutUint16(data[62:], 1)
	binary.LittleEndian.PutUint64(data[128+24:], 192)
	binary.LittleEndian.PutUint64(data[128+32:], 64)
	return data
}

func TestELFHeaderBounds(t *testing.T) {
	if err := validateELFHeader(elfHeaderFixture()); err != nil {
		t.Fatalf("valid control rejected: %v", err)
	}
	tests := []struct {
		name   string
		mutate func([]byte) []byte
	}{
		{"short", func(d []byte) []byte { return d[:63] }},
		{"non ELF", func(d []byte) []byte { d[0] = 0; return d }},
		{"wrong byte order", func(d []byte) []byte { d[5] = 2; return d }},
		{"extended numbering", func(d []byte) []byte { binary.LittleEndian.PutUint16(d[60:], 0); return d }},
		{"section table offset overflow", func(d []byte) []byte {
			binary.LittleEndian.PutUint64(d[40:], ^uint64(0))
			return d
		}},
		{"section table truncation", func(d []byte) []byte { return d[:160] }},
		{"invalid names index", func(d []byte) []byte { binary.LittleEndian.PutUint16(d[62:], 3); return d }},
		{"compressed names", func(d []byte) []byte {
			binary.LittleEndian.PutUint64(d[128+8:], uint64(elf.SHF_COMPRESSED))
			return d
		}},
		{"oversized names", func(d []byte) []byte {
			binary.LittleEndian.PutUint64(d[128+32:], ^uint64(0))
			return d
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if err := validateELFHeader(test.mutate(elfHeaderFixture())); err == nil {
				t.Fatal("malformed ELF bounds accepted")
			}
		})
	}
}

func TestModuleEvidencePreservesUncertainReplacement(t *testing.T) {
	m := debug.Module{Path: "example.org/dependency", Version: "v1.2.3", Sum: "h1:upstream", Replace: &debug.Module{Path: "../local", Version: "(devel)"}}
	evidence := module(m, "dependency")
	if evidence.Path != m.Path || evidence.Version != m.Version || evidence.Sum != m.Sum || evidence.Replace == nil || evidence.Replace.Path != "../local" || evidence.Replace.Version != "(devel)" {
		t.Fatalf("replacement provenance lost: %+v", evidence)
	}
	if moduleMetadataKnown(m) {
		t.Fatal("local replacement claimed complete version evidence")
	}
	for _, uncertain := range []debug.Module{{}, {Path: "example.org/main"}, {Path: "example.org/main", Version: "(devel)"}} {
		if moduleMetadataKnown(uncertain) {
			t.Fatalf("uncertain module claimed complete: %+v", uncertain)
		}
	}
}

func TestInputBounds(t *testing.T) {
	dir := t.TempDir()
	empty := filepath.Join(dir, "empty")
	if err := os.WriteFile(empty, nil, 0600); err != nil {
		t.Fatal(err)
	}
	oversized := filepath.Join(dir, "oversized")
	file, err := os.Create(oversized)
	if err != nil {
		t.Fatal(err)
	}
	if err := file.Truncate(maxFileSize + 1); err != nil {
		file.Close()
		t.Fatal(err)
	}
	file.Close()
	for _, path := range []string{empty, oversized, dir, filepath.Join(dir, "missing")} {
		var evidence report
		if err := inspect(path, &evidence); err == nil {
			t.Errorf("invalid input %q accepted", path)
		}
		if evidence.SymbolCount != 0 || evidence.SymbolTableSHA256 != "" {
			t.Fatalf("invalid input produced symbol proof: %+v", evidence)
		}
	}
}

func fixtureEnvironment(arch string) []string {
	values := map[string]string{"GOOS": "linux", "GOARCH": arch, "CGO_ENABLED": "0", "GOTOOLCHAIN": "local", "GOWORK": "off", "GOPROXY": "off", "GOSUMDB": "off", "GOFLAGS": ""}
	var env []string
	for _, value := range os.Environ() {
		key, _, _ := strings.Cut(value, "=")
		if _, overridden := values[key]; !overridden {
			env = append(env, value)
		}
	}
	for key, value := range values {
		env = append(env, key+"="+value)
	}
	return env
}

func TestHostedActualBinaryEvidence(t *testing.T) {
	// Test fixtures are compiled only by the hosted runner running this test.
	// Neither this test nor the collector executes a target binary.
	dir := t.TempDir()
	dep := filepath.Join(dir, "dep")
	if err := os.Mkdir(dep, 0700); err != nil {
		t.Fatal(err)
	}
	files := map[string]string{
		"go.mod":     "module desktop.test/main\n\ngo 1.18\n\nrequire desktop.test/dep v1.2.3\nreplace desktop.test/dep => ./dep\n",
		"main.go":    "package main\nimport (\"fmt\"; \"desktop.test/dep\")\nfunc main() { fmt.Println(dep.KeptFunction()) }\n",
		"dep/go.mod": "module desktop.test/dep\n\ngo 1.18\n",
		"dep/dep.go": "package dep\n//go:noinline\nfunc KeptFunction() int { return 7 }\n",
	}
	for name, content := range files {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
	}
	for _, mode := range []string{"exe", "pie", "arm64"} {
		t.Run(mode, func(t *testing.T) {
			arch, buildmode := "amd64", mode
			if mode == "arm64" {
				arch, buildmode = "arm64", "exe"
			}
			path := filepath.Join(dir, "fixture-"+mode)
			cmd := exec.Command("go", "build", "-mod=readonly", "-trimpath", "-ldflags=-s -w", "-buildmode="+buildmode, "-o", path, ".")
			cmd.Dir, cmd.Env = dir, fixtureEnvironment(arch)
			if output, err := cmd.CombinedOutput(); err != nil {
				t.Fatalf("hosted fixture compilation failed: %v\n%s", err, output)
			}
			evidence := report{AbsenceNotProof: true, SymbolCoverage: "unknown", ModuleCoverage: "unknown"}
			err := inspect(path, &evidence)
			if mode == "arm64" {
				if err == nil || !strings.Contains(err.Error(), "amd64") {
					t.Fatalf("wrong architecture not explicitly rejected: %v", err)
				}
				return
			}
			if err != nil {
				t.Fatalf("actual stripped %s binary rejected: %v", mode, err)
			}
			data, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			hash := sha256.Sum256(data)
			if evidence.SHA256 != hex.EncodeToString(hash[:]) || evidence.Size != int64(len(data)) {
				t.Fatal("binary hash/size does not bind evidence to exact fixture bytes")
			}
			if evidence.OS != "linux" || evidence.Arch != "amd64" || !supportedVersion(evidence.GoVersion) || evidence.SymbolCoverage != "pclntab-functions-only" || !evidence.AbsenceNotProof {
				t.Fatalf("provenance or coverage claims invalid: %+v", evidence)
			}
			if evidence.SymbolCount != len(evidence.Symbols) || evidence.SymbolCount == 0 || !sort.StringsAreSorted(evidence.Symbols) {
				t.Fatal("missing, unsorted, or inconsistent function evidence")
			}
			foundFunction := false
			for i, symbol := range evidence.Symbols {
				if i > 0 && evidence.Symbols[i-1] == symbol {
					t.Fatal("duplicate function names were not removed")
				}
				foundFunction = foundFunction || symbol == "desktop.test/dep.KeptFunction"
			}
			if !foundFunction {
				t.Fatal("known linked Go function absent from concrete symbol evidence")
			}
			symbolHash := sha256.Sum256([]byte(strings.Join(evidence.Symbols, "\n") + "\n"))
			if evidence.SymbolTableSHA256 != hex.EncodeToString(symbolHash[:]) {
				t.Fatal("canonical symbol-table hash mismatch")
			}
			foundReplacement := false
			for _, m := range evidence.Modules {
				// cmd/go records local replacements with version "(devel)".
				// Preserve that explicit uncertainty rather than inventing a version.
				if m.Path == "desktop.test/dep" && m.Version == "v1.2.3" && m.Replace != nil && m.Replace.Path == "./dep" && m.Replace.Version == "(devel)" {
					foundReplacement = true
				}
			}
			if !foundReplacement || evidence.ModuleCoverage != "unknown" {
				t.Fatalf("development/local-replacement module uncertainty lost: coverage=%q modules=%+v", evidence.ModuleCoverage, evidence.Modules)
			}
			if mode == "exe" {
				// Change only the recorded compiler version with an equal-length
				// unsupported release. Platform/modules must survive unknown symbols.
				versionParts := releasedGo.FindStringSubmatch(evidence.GoVersion)
				if versionParts == nil || len(versionParts[1]) != 2 {
					t.Fatalf("fixture toolchain version unexpected: %q", evidence.GoVersion)
				}
				unknownVersion := strings.Replace(evidence.GoVersion, "go1."+versionParts[1], "go1.99", 1)
				changed := bytes.ReplaceAll(data, []byte(evidence.GoVersion), []byte(unknownVersion))
				unknownPath := filepath.Join(dir, "fixture-unknown-version")
				if err := os.WriteFile(unknownPath, changed, 0600); err != nil {
					t.Fatal(err)
				}
				unknown := report{AbsenceNotProof: true, SymbolCoverage: "unknown", ModuleCoverage: "unknown"}
				err := inspect(unknownPath, &unknown)
				if err == nil || !strings.Contains(err.Error(), "unsupported Go version") || unknown.GoVersion != unknownVersion || unknown.OS != "linux" || unknown.Arch != "amd64" || len(unknown.Modules) != len(evidence.Modules) || len(unknown.BuildSettings) == 0 || unknown.SymbolCount != 0 || unknown.SymbolCoverage != "unknown" {
					t.Fatalf("unsupported symbol format lost independent metadata: version=%q os=%q arch=%q modules=%d symbols=%d error=%v", unknown.GoVersion, unknown.OS, unknown.Arch, len(unknown.Modules), unknown.SymbolCount, err)
				}
			}
		})
	}
}

func TestCLIHelper(t *testing.T) {
	if os.Getenv("GO_BINARY_EVIDENCE_HELPER") != "1" {
		return
	}
	separator := -1
	for i, arg := range os.Args {
		if arg == "--" {
			separator = i
			break
		}
	}
	if separator < 0 {
		os.Exit(2)
	}
	os.Args = append([]string{"go-binary-evidence"}, os.Args[separator+1:]...)
	main()
	os.Exit(0)
}

func TestCLIErrorRetainsUnknown(t *testing.T) {
	path := filepath.Join(t.TempDir(), "not-a-Go-binary")
	if err := os.WriteFile(path, []byte("untrusted non-ELF input"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{nil, {path}} {
		commandArgs := append([]string{"-test.run=^TestCLIHelper$", "--"}, args...)
		cmd := exec.Command(os.Args[0], commandArgs...)
		cmd.Env = append(os.Environ(), "GO_BINARY_EVIDENCE_HELPER=1")
		var stderr bytes.Buffer
		cmd.Stderr = &stderr
		output, err := cmd.Output()
		if err == nil {
			t.Fatalf("invalid CLI input exited successfully: %s", output)
		}
		var evidence report
		if err := json.Unmarshal(output, &evidence); err != nil {
			t.Fatalf("error response is not JSON: %v; stdout=%s stderr=%s", err, output, stderr.String())
		}
		if evidence.Schema != 1 || evidence.Status != "error" || evidence.Error == "" || evidence.SymbolCoverage != "unknown" || !evidence.AbsenceNotProof || evidence.SymbolCount != 0 || len(evidence.Symbols) != 0 || evidence.SymbolTableSHA256 != "" {
			t.Fatalf("invalid input emitted clearance-like evidence: %+v", evidence)
		}
	}
}
