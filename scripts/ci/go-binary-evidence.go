// go-binary-evidence extracts evidence without executing the inspected file.
// Run only on hosted validation runners. Pclntab function names do not include
// every inlined function, so absence is not proof that vulnerable code is absent.
package main

import (
	"bytes"
	"crypto/sha256"
	"debug/buildinfo"
	"debug/elf"
	"debug/gosym"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"regexp"
	"runtime/debug"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

const maxFileSize = 256 << 20

type moduleEvidence struct {
	Kind    string          `json:"kind,omitempty"`
	Path    string          `json:"path"`
	Version string          `json:"version"`
	Sum     string          `json:"sum,omitempty"`
	Replace *moduleEvidence `json:"replace,omitempty"`
}

type report struct {
	Schema            int                  `json:"schema"`
	Status            string               `json:"status"`
	Error             string               `json:"error,omitempty"`
	SHA256            string               `json:"sha256"`
	Size              int64                `json:"size"`
	OS                string               `json:"os"`
	Arch              string               `json:"arch"`
	GoVersion         string               `json:"goVersion"`
	Modules           []moduleEvidence     `json:"modules"`
	BuildSettings     []debug.BuildSetting `json:"buildSettings"`
	SymbolCount       int                  `json:"symbolCount"`
	Symbols           []string             `json:"symbols"`
	SymbolTableSHA256 string               `json:"symbolTableSha256"`
	SymbolCoverage    string               `json:"symbolCoverage"`
	AbsenceNotProof   bool                 `json:"absenceNotProof"`
	ModuleCoverage    string               `json:"moduleCoverage"`
	TextAddressSource string               `json:"textAddressSource,omitempty"`
}

func module(m debug.Module, kind string) moduleEvidence {
	r := moduleEvidence{Kind: kind, Path: m.Path, Version: m.Version, Sum: m.Sum}
	if m.Replace != nil {
		replacement := module(*m.Replace, "")
		r.Replace = &replacement
	}
	return r
}

// These released Go versions use the reviewed 1.18/1.20 pclntab formats.
// A future version requires an explicit format review instead of a silent pass.
var releasedGo = regexp.MustCompile(`^go1\.([0-9]+)(?:\.[0-9]+)?$`)

func supportedVersion(v string) bool {
	// Fedora's exact reviewed variant disables DWARF5; it does not change
	// pclntab. Keep the raw version in the report and reject other experiments.
	if strings.HasSuffix(v, "-X:nodwarf5") {
		base := strings.TrimSuffix(v, "-X:nodwarf5")
		m := releasedGo.FindStringSubmatch(base)
		return m != nil && m[1] == "26"
	}
	m := releasedGo.FindStringSubmatch(v)
	if m == nil {
		return false
	}
	minor, err := strconv.Atoi(m[1])
	return err == nil && minor >= 18 && minor <= 27
}

func sectionData(f *elf.File, name string, fileSize uint64) ([]byte, error) {
	s := f.Section(name)
	if s == nil {
		return nil, nil
	}
	if s.Flags&elf.SHF_COMPRESSED != 0 || s.Type == elf.SHT_NOBITS || s.Size > fileSize || s.Offset > fileSize || s.Size > fileSize-s.Offset {
		return nil, fmt.Errorf("unsafe section bounds or encoding: %s", name)
	}
	data, err := s.Data()
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", name, err)
	}
	return data, nil
}

// Validate counts and section offsets before gosym may allocate from them.
func validatePCLN(data []byte, text *elf.Section) (uint64, uint64, error) {
	if len(data) < 72 || data[4] != 0 || data[5] != 0 || data[6] != 1 || data[7] != 8 {
		return 0, 0, fmt.Errorf("unsupported or malformed amd64 pclntab header")
	}
	magic := binary.LittleEndian.Uint32(data)
	if magic != 0xfffffff0 && magic != 0xfffffff1 {
		return 0, 0, fmt.Errorf("unsupported pclntab magic %#x", magic)
	}
	word := func(i int) uint64 { return binary.LittleEndian.Uint64(data[8+i*8:]) }
	nfunc, nfile, textStart := word(0), word(1), word(2)
	if nfunc == 0 || nfunc > 500000 || nfile > 250000 || nfunc > uint64(len(data))/16 || nfile > uint64(len(data))/4 {
		return 0, 0, fmt.Errorf("pclntab count exceeds bounded section capacity")
	}
	previous := uint64(72)
	for i := 3; i <= 7; i++ {
		offset := word(i)
		if offset < previous || offset >= uint64(len(data)) {
			return 0, 0, fmt.Errorf("invalid pclntab section offset %d", i)
		}
		previous = offset
	}
	funcOffset := word(7)
	if (nfunc*2+1)*4 > uint64(len(data))-funcOffset {
		return 0, 0, fmt.Errorf("truncated pclntab function table")
	}
	if text == nil || text.Size == 0 || text.Flags&elf.SHF_EXECINSTR == 0 || text.Addr > ^uint64(0)-text.Size || (textStart != 0 && (textStart < text.Addr || textStart >= text.Addr+text.Size)) {
		return 0, 0, fmt.Errorf("pclntab runtime.text is outside executable .text")
	}
	return nfunc, textStart, nil
}

func resolveTextAddress(start uint64, version string, settings map[string]string, text *elf.Section) (uint64, string, error) {
	if start != 0 {
		return start, "pclntab-header", nil
	}
	// Go 1.26's linker deliberately zeroes the former textStart word. Its
	// layout and names are unchanged. Use section-relative addresses only for
	// gc binaries without cgo; cgo runtime.text may differ from .text.Addr.
	base := strings.TrimSuffix(version, "-X:nodwarf5")
	m := releasedGo.FindStringSubmatch(base)
	if m == nil || (m[1] != "26" && m[1] != "27") || settings["CGO_ENABLED"] != "0" || settings["-compiler"] != "gc" || (settings["-buildmode"] != "exe" && settings["-buildmode"] != "pie") || text == nil {
		return 0, "", fmt.Errorf("pclntab text address is unused or unrelocated; exact runtime.text is unknown for this build")
	}
	return text.Addr, "elf-text-section-relative-cgo-disabled", nil
}

// Bound the ELF name table before debug/elf can allocate or decompress it.
// Extended section numbering is deliberately unknown for this narrow probe.
func validateELFHeader(data []byte) error {
	if len(data) < 64 || !bytes.Equal(data[:4], []byte{0x7f, 'E', 'L', 'F'}) || data[4] != 2 || data[5] != 1 {
		return fmt.Errorf("expected 64-bit little-endian ELF")
	}
	sectionOffset := binary.LittleEndian.Uint64(data[40:])
	entrySize := uint64(binary.LittleEndian.Uint16(data[58:]))
	count := uint64(binary.LittleEndian.Uint16(data[60:]))
	nameIndex := uint64(binary.LittleEndian.Uint16(data[62:]))
	if entrySize != 64 || count == 0 || nameIndex == 0 || nameIndex >= count || sectionOffset > uint64(len(data)) || count*entrySize > uint64(len(data))-sectionOffset {
		return fmt.Errorf("invalid, absent, or extended ELF section table")
	}
	nameHeader := data[sectionOffset+nameIndex*entrySize:]
	flags := binary.LittleEndian.Uint64(nameHeader[8:])
	offset := binary.LittleEndian.Uint64(nameHeader[24:])
	size := binary.LittleEndian.Uint64(nameHeader[32:])
	if flags&uint64(elf.SHF_COMPRESSED) != 0 || offset > uint64(len(data)) || size > uint64(len(data))-offset {
		return fmt.Errorf("unsafe ELF section-name table bounds or encoding")
	}
	return nil
}

func moduleMetadataKnown(m debug.Module) bool {
	if m.Path == "" || m.Version == "" || m.Version == "(devel)" {
		return false
	}
	return m.Replace == nil || (m.Replace.Path != "" && m.Replace.Version != "" && m.Replace.Version != "(devel)")
}

func inspect(path string, r *report) (err error) {
	// The standard debug parsers can panic on malformed input. Preserve an
	// explicit unknown/error result rather than emitting incomplete evidence.
	defer func() {
		if recovered := recover(); recovered != nil {
			err = fmt.Errorf("malformed binary metadata (parser panic)")
		}
	}()
	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open input: %w", err)
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return fmt.Errorf("input must be a readable regular file")
	}
	r.Size = info.Size()
	if r.Size <= 0 || r.Size > maxFileSize {
		return fmt.Errorf("input size must be 1..%d bytes", maxFileSize)
	}
	data, err := io.ReadAll(io.LimitReader(file, maxFileSize+1))
	if err != nil || int64(len(data)) != r.Size {
		return fmt.Errorf("input read failed or size changed during inspection")
	}
	hash := sha256.Sum256(data)
	r.SHA256 = hex.EncodeToString(hash[:])
	if err := validateELFHeader(data); err != nil {
		return err
	}
	f, err := elf.NewFile(bytes.NewReader(data))
	if err != nil {
		return fmt.Errorf("read ELF: %w", err)
	}
	defer f.Close()
	if f.Machine != elf.EM_X86_64 || f.Class != elf.ELFCLASS64 || f.Data != elf.ELFDATA2LSB || (f.Type != elf.ET_EXEC && f.Type != elf.ET_DYN) {
		return fmt.Errorf("only executable Linux amd64 little-endian ELF is supported")
	}
	build, err := buildinfo.Read(bytes.NewReader(data))
	if err != nil {
		return fmt.Errorf("read Go build information: %w", err)
	}
	r.GoVersion = build.GoVersion
	r.BuildSettings = build.Settings
	settings := make(map[string]string)
	for _, setting := range build.Settings {
		if _, exists := settings[setting.Key]; exists {
			return fmt.Errorf("duplicate Go build setting %q", setting.Key)
		}
		settings[setting.Key] = setting.Value
	}
	if settings["GOOS"] != "linux" || settings["GOARCH"] != "amd64" {
		return fmt.Errorf("build information must explicitly prove GOOS=linux and GOARCH=amd64")
	}
	r.OS, r.Arch = "linux", "amd64"
	r.ModuleCoverage = "recorded"
	if !moduleMetadataKnown(build.Main) {
		r.ModuleCoverage = "unknown"
	}
	r.Modules = append(r.Modules, module(build.Main, "main"))
	for _, dep := range build.Deps {
		if dep == nil {
			return fmt.Errorf("nil Go module metadata")
		}
		r.Modules = append(r.Modules, module(*dep, "dependency"))
		if !moduleMetadataKnown(*dep) {
			r.ModuleCoverage = "unknown"
		}
	}
	if !supportedVersion(build.GoVersion) {
		return fmt.Errorf("unsupported Go version %q; reviewed releases are Go 1.18 through 1.27 and the exact Go 1.26 nodwarf5 variant", build.GoVersion)
	}
	pcln, err := sectionData(f, ".gopclntab", uint64(len(data)))
	if err != nil {
		return err
	}
	if len(pcln) == 0 {
		pcln, err = sectionData(f, ".data.rel.ro.gopclntab", uint64(len(data)))
		if err != nil {
			return err
		}
	}
	if len(pcln) == 0 {
		return fmt.Errorf("Go pclntab section is missing; function coverage is unknown")
	}
	count, textStart, err := validatePCLN(pcln, f.Section(".text"))
	if err != nil {
		return err
	}
	textStart, r.TextAddressSource, err = resolveTextAddress(textStart, build.GoVersion, settings, f.Section(".text"))
	if err != nil {
		return err
	}
	symtab, err := sectionData(f, ".gosymtab", uint64(len(data)))
	if err != nil {
		return err
	}
	if len(symtab) == 0 {
		symtab, err = sectionData(f, ".data.rel.ro.gosymtab", uint64(len(data)))
		if err != nil {
			return err
		}
	}
	table, err := gosym.NewTable(symtab, gosym.NewLineTable(pcln, textStart))
	if err != nil || table == nil {
		return fmt.Errorf("decode Go symbol table: %v", err)
	}
	if uint64(len(table.Funcs)) != count {
		return fmt.Errorf("decoded function count does not match pclntab header")
	}
	text := f.Section(".text")
	seen := make(map[string]bool, len(table.Funcs))
	var previousEnd uint64
	for _, fn := range table.Funcs {
		if fn.Sym == nil || fn.Name == "" || len(fn.Name) > 4096 || !utf8.ValidString(fn.Name) || strings.ContainsAny(fn.Name, "\x00\r\n") {
			return fmt.Errorf("invalid or oversized pclntab function name")
		}
		if fn.Entry < text.Addr || fn.End <= fn.Entry || fn.End > text.Addr+text.Size || (previousEnd != 0 && fn.Entry < previousEnd) {
			return fmt.Errorf("function addresses are outside .text or overlap")
		}
		previousEnd = fn.End
		seen[fn.Name] = true
	}
	for name := range seen {
		r.Symbols = append(r.Symbols, name)
	}
	sort.Strings(r.Symbols)
	r.SymbolCount = len(r.Symbols)
	// Canonical hash: sorted distinct UTF-8 names, each followed by LF.
	symbolHash := sha256.New()
	for _, name := range r.Symbols {
		io.WriteString(symbolHash, name+"\n")
	}
	r.SymbolTableSHA256 = hex.EncodeToString(symbolHash.Sum(nil))
	r.SymbolCoverage = "pclntab-functions-only"
	return nil
}

func main() {
	r := report{Schema: 1, Status: "error", Modules: []moduleEvidence{}, BuildSettings: []debug.BuildSetting{}, Symbols: []string{}, SymbolCoverage: "unknown", AbsenceNotProof: true, ModuleCoverage: "unknown"}
	var err error
	if len(os.Args) != 2 {
		err = fmt.Errorf("usage: go-binary-evidence ELF_FILE")
	} else {
		err = inspect(os.Args[1], &r)
	}
	if err != nil {
		r.Error = err.Error()
		r.Symbols = []string{}
		r.SymbolCount = 0
		r.SymbolTableSHA256 = ""
		r.SymbolCoverage = "unknown"
	} else {
		r.Status = "ok"
	}
	if err := json.NewEncoder(os.Stdout).Encode(r); err != nil {
		fmt.Fprintln(os.Stderr, "encode evidence:", err)
		os.Exit(1)
	}
	if r.Status != "ok" {
		os.Exit(1)
	}
}
