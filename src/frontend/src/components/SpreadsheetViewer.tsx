import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import * as XLSX from "xlsx";
import {
  Search,
  Download,
  FileSpreadsheet,
  AlertCircle,
  Loader2,
  Table,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Copy,
  Check,
  RotateCcw
} from "lucide-react";
import { toast } from "sonner";

interface SpreadsheetViewerProps {
  url: string;
  fileName: string;
}

export const SpreadsheetViewer = ({ url, fileName }: SpreadsheetViewerProps) => {
  const [workbook, setWorkbook] = useState<XLSX.WorkBook | null>(null);
  const [sheetNames, setSheetNames] = useState<string[]>([]);
  const [activeSheet, setActiveSheet] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Grid data
  const [sheetData, setSheetData] = useState<(string | number | boolean | null)[][]>([]);
  const [activeCell, setActiveCell] = useState<{ row: number; col: number } | null>({ row: 0, col: 0 });
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [fontSize, setFontSize] = useState<number>(13);
  const [copiedCell, setCopiedCell] = useState<boolean>(false);

  // Pagination for very large sheets (e.g. > 1000 rows)
  const [page, setPage] = useState<number>(1);
  const ROWS_PER_PAGE = 500;

  const tableContainerRef = useRef<HTMLDivElement>(null);

  // Load workbook from URL
  useEffect(() => {
    let isMounted = true;
    setIsLoading(true);
    setError(null);

    const fetchAndParse = async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`Failed to load file (${response.status})`);
        }
        const arrayBuffer = await response.arrayBuffer();

        // Parse with SheetJS
        const wb = XLSX.read(arrayBuffer, {
          type: "array",
          cellDates: true,
          cellFormula: true,
          cellStyles: true,
          dense: true,
        });

        if (!isMounted) return;

        if (!wb.SheetNames || wb.SheetNames.length === 0) {
          throw new Error("No sheets found in spreadsheet");
        }

        setWorkbook(wb);
        setSheetNames(wb.SheetNames);
        setActiveSheet(wb.SheetNames[0]);
      } catch (err: any) {
        if (!isMounted) return;
        console.error("Spreadsheet parse error:", err);
        setError(err.message || "Failed to parse spreadsheet");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    };

    fetchAndParse();

    return () => {
      isMounted = false;
    };
  }, [url]);

  // When activeSheet changes, parse sheet data into 2D array
  useEffect(() => {
    if (!workbook || !activeSheet) return;

    try {
      const sheet = workbook.Sheets[activeSheet];
      if (!sheet) {
        setSheetData([]);
        return;
      }

      // Parse sheet to 2D array
      const rawData: (string | number | boolean | null)[][] = XLSX.utils.sheet_to_json(sheet, {
        header: 1,
        defval: "",
        blankrows: true,
        raw: false, // get formatted text representation
      });

      setSheetData(rawData);
      setPage(1);
      setActiveCell({ row: 0, col: 0 });
    } catch (err: any) {
      console.error("Error reading sheet:", err);
      toast.error(`Failed to display sheet: ${activeSheet}`);
    }
  }, [workbook, activeSheet]);

  // Determine max columns
  const maxCols = useMemo(() => {
    let max = 0;
    for (const row of sheetData) {
      if (row && row.length > max) {
        max = row.length;
      }
    }
    return Math.max(max, 10); // Minimum 10 columns for standard Excel feel
  }, [sheetData]);

  // Filter rows if searching
  const filteredRows = useMemo(() => {
    if (!searchQuery.trim()) {
      return sheetData.map((row, idx) => ({ row, origIdx: idx }));
    }
    const q = searchQuery.toLowerCase();
    return sheetData
      .map((row, idx) => ({ row, origIdx: idx }))
      .filter(({ row }) =>
        row?.some((cell) => cell !== null && cell !== undefined && String(cell).toLowerCase().includes(q))
      );
  }, [sheetData, searchQuery]);

  // Paginated slice
  const paginatedRows = useMemo(() => {
    const start = (page - 1) * ROWS_PER_PAGE;
    return filteredRows.slice(start, start + ROWS_PER_PAGE);
  }, [filteredRows, page]);

  const totalPages = Math.ceil(filteredRows.length / ROWS_PER_PAGE) || 1;

  // Active cell coordinate & value
  const activeCellCoord = useMemo(() => {
    if (!activeCell) return "A1";
    const colName = XLSX.utils.encode_col(activeCell.col);
    const rowName = activeCell.row + 1;
    return `${colName}${rowName}`;
  }, [activeCell]);

  const activeCellValue = useMemo(() => {
    if (!activeCell || !sheetData[activeCell.row]) return "";
    const val = sheetData[activeCell.row][activeCell.col];
    return val !== null && val !== undefined ? String(val) : "";
  }, [activeCell, sheetData]);

  // Export current sheet as CSV
  const handleExportCSV = useCallback(() => {
    if (!workbook || !activeSheet) return;
    try {
      const sheet = workbook.Sheets[activeSheet];
      const csvContent = XLSX.utils.sheet_to_csv(sheet);
      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const dlUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = dlUrl;
      a.download = `${fileName.replace(/\.[^/.]+$/, "")}_${activeSheet}.csv`;
      a.click();
      URL.revokeObjectURL(dlUrl);
      toast.success(`Exported ${activeSheet} as CSV`);
    } catch (err: any) {
      toast.error("Failed to export CSV");
    }
  }, [workbook, activeSheet, fileName]);

  // Copy cell value
  const handleCopyCell = useCallback(() => {
    if (!activeCellValue) return;
    navigator.clipboard.writeText(activeCellValue);
    setCopiedCell(true);
    toast.success("Cell value copied!");
    setTimeout(() => setCopiedCell(false), 1500);
  }, [activeCellValue]);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!activeCell) return;

      const { row, col } = activeCell;
      if (e.key === "ArrowUp" && row > 0) {
        e.preventDefault();
        setActiveCell({ row: row - 1, col });
      } else if (e.key === "ArrowDown" && row < sheetData.length - 1) {
        e.preventDefault();
        setActiveCell({ row: row + 1, col });
      } else if (e.key === "ArrowLeft" && col > 0) {
        e.preventDefault();
        setActiveCell({ row, col: col - 1 });
      } else if (e.key === "ArrowRight" && col < maxCols - 1) {
        e.preventDefault();
        setActiveCell({ row, col: col + 1 });
      } else if (e.key === "Tab") {
        e.preventDefault();
        if (e.shiftKey && col > 0) {
          setActiveCell({ row, col: col - 1 });
        } else if (!e.shiftKey && col < maxCols - 1) {
          setActiveCell({ row, col: col + 1 });
        }
      }
    },
    [activeCell, sheetData.length, maxCols]
  );

  if (isLoading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center min-h-[400px] gap-3 text-muted-foreground">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
        <p className="text-sm font-medium">Reading spreadsheet contents...</p>
        <p className="text-xs opacity-60">Parsing sheets, rows and columns</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center min-h-[400px] gap-3 text-center p-6">
        <AlertCircle className="w-10 h-10 text-destructive" />
        <p className="text-base font-semibold text-foreground">Failed to display spreadsheet</p>
        <p className="text-sm text-muted-foreground max-w-md">{error}</p>
      </div>
    );
  }

  return (
    <div
      className="flex-1 flex flex-col h-full overflow-hidden bg-background text-foreground select-none"
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      {/* Top Toolbar */}
      <div className="px-4 py-2 border-b border-border/80 bg-muted/40 flex flex-wrap items-center justify-between gap-3 shrink-0">
        {/* Left: Active sheet indicator & Search */}
        <div className="flex items-center gap-2.5 flex-1 min-w-[240px]">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 text-xs font-medium">
            <FileSpreadsheet className="w-3.5 h-3.5" />
            <span>Excel View</span>
          </div>

          <div className="relative flex-1 max-w-xs">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search in sheet..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(1);
              }}
              className="w-full pl-8 pr-3 py-1 text-xs rounded-md bg-background border border-border focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {searchQuery && (
            <span className="text-[11px] text-muted-foreground whitespace-nowrap">
              {filteredRows.length} matches
            </span>
          )}
        </div>

        {/* Right: Zoom & Export */}
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={() => setFontSize((s) => Math.max(10, s - 1))}
            className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
            title="Zoom out"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-[11px] font-mono text-muted-foreground px-1">{fontSize}px</span>
          <button
            onClick={() => setFontSize((s) => Math.min(18, s + 1))}
            className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
            title="Zoom in"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>

          <div className="h-4 w-px bg-border mx-1" />

          <button
            onClick={handleExportCSV}
            className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-accent/60 hover:bg-accent text-xs text-foreground transition-colors"
            title="Export this sheet as CSV"
          >
            <Download className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Export CSV</span>
          </button>
        </div>
      </div>

      {/* Formula & Active Cell Bar */}
      <div className="px-3 py-1.5 border-b border-border/60 bg-muted/20 flex items-center gap-2 shrink-0 font-mono text-xs">
        <div className="flex items-center justify-center w-14 py-0.5 px-2 bg-muted rounded border border-border/80 font-semibold text-primary text-center">
          {activeCellCoord}
        </div>
        <div className="text-muted-foreground/60 select-none">fx</div>
        <div className="flex-1 px-2 py-0.5 bg-background/80 rounded border border-border/60 truncate text-foreground flex items-center justify-between">
          <span className="truncate">{activeCellValue || <span className="text-muted-foreground/40 italic">empty</span>}</span>
          {activeCellValue && (
            <button
              onClick={handleCopyCell}
              className="p-1 text-muted-foreground hover:text-foreground shrink-0 ml-2"
              title="Copy cell value"
            >
              {copiedCell ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
            </button>
          )}
        </div>
      </div>

      {/* Spreadsheet Grid Table */}
      <div
        ref={tableContainerRef}
        className="flex-1 overflow-auto bg-background relative focus:outline-none"
        style={{ fontSize: `${fontSize}px` }}
      >
        <table className="border-collapse min-w-full table-fixed">
          <thead>
            <tr className="sticky top-0 z-20 bg-muted/80 backdrop-blur-sm shadow-sm">
              {/* Corner Top-Left Cell */}
              <th className="w-12 min-w-[48px] max-w-[48px] p-1 border border-border/80 bg-muted/90 text-center text-xs font-semibold text-muted-foreground sticky left-0 z-30">
                #
              </th>
              {/* Column Headers: A, B, C... */}
              {Array.from({ length: maxCols }).map((_, cIdx) => {
                const colHeader = XLSX.utils.encode_col(cIdx);
                const isCurrentCol = activeCell?.col === cIdx;
                return (
                  <th
                    key={cIdx}
                    className={`min-w-[110px] max-w-[200px] px-2 py-1.5 border border-border/80 font-mono font-medium text-center truncate ${
                      isCurrentCol
                        ? "bg-primary/20 text-primary border-primary/50 font-semibold"
                        : "text-muted-foreground hover:bg-accent/40"
                    }`}
                  >
                    {colHeader}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {paginatedRows.length === 0 ? (
              <tr>
                <td
                  colSpan={maxCols + 1}
                  className="py-16 text-center text-muted-foreground italic text-sm"
                >
                  {searchQuery ? "No matching cells found" : "Sheet is empty"}
                </td>
              </tr>
            ) : (
              paginatedRows.map(({ row, origIdx }) => {
                const isCurrentRow = activeCell?.row === origIdx;
                return (
                  <tr key={origIdx} className="hover:bg-accent/20 transition-colors">
                    {/* Row Number Header: 1, 2, 3... */}
                    <td
                      className={`w-12 min-w-[48px] max-w-[48px] px-1 py-1 border border-border/80 text-center font-mono text-[11px] sticky left-0 z-10 select-none ${
                        isCurrentRow
                          ? "bg-primary/20 text-primary font-bold border-primary/50"
                          : "bg-muted/70 text-muted-foreground"
                      }`}
                    >
                      {origIdx + 1}
                    </td>

                    {/* Row Cells */}
                    {Array.from({ length: maxCols }).map((_, cIdx) => {
                      const cellVal = row && row[cIdx] !== undefined && row[cIdx] !== null ? row[cIdx] : "";
                      const isSelected = activeCell?.row === origIdx && activeCell?.col === cIdx;
                      const isNumeric = typeof cellVal === "number" || (!isNaN(Number(cellVal)) && String(cellVal).trim() !== "");

                      return (
                        <td
                          key={cIdx}
                          onClick={() => setActiveCell({ row: origIdx, col: cIdx })}
                          className={`px-2 py-1 border border-border/60 truncate cursor-cell transition-all font-sans ${
                            isSelected
                              ? "bg-primary/15 outline outline-2 outline-primary z-10 text-foreground font-medium"
                              : "text-foreground/90 hover:bg-accent/30"
                          } ${isNumeric ? "text-right font-mono" : "text-left"}`}
                          title={String(cellVal)}
                        >
                          {String(cellVal)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer (if sheet > ROWS_PER_PAGE) */}
      {totalPages > 1 && (
        <div className="px-4 py-1.5 border-t border-border/60 bg-muted/20 flex items-center justify-between text-xs text-muted-foreground shrink-0">
          <span>
            Showing rows {(page - 1) * ROWS_PER_PAGE + 1}–{Math.min(page * ROWS_PER_PAGE, filteredRows.length)} of {filteredRows.length}
          </span>
          <div className="flex items-center gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="p-1 rounded hover:bg-accent disabled:opacity-30"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="font-mono">{page} / {totalPages}</span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="p-1 rounded hover:bg-accent disabled:opacity-30"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Bottom Sheets Tab Strip (Google Sheets / Excel Style) */}
      <div className="px-2 py-1 border-t border-border bg-muted/60 flex items-center justify-between gap-2 shrink-0 overflow-x-auto">
        <div className="flex items-center gap-1 min-w-0 overflow-x-auto py-0.5">
          {sheetNames.map((name) => {
            const isActive = name === activeSheet;
            return (
              <button
                key={name}
                onClick={() => setActiveSheet(name)}
                className={`px-3 py-1 text-xs rounded-md font-medium transition-all whitespace-nowrap flex items-center gap-1.5 ${
                  isActive
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "bg-background/80 hover:bg-background text-muted-foreground hover:text-foreground border border-border/50"
                }`}
              >
                <Table className="w-3 h-3" />
                <span>{name}</span>
              </button>
            );
          })}
        </div>

        <div className="text-[11px] text-muted-foreground/70 shrink-0 font-mono hidden sm:block">
          {sheetData.length} rows • {maxCols} cols
        </div>
      </div>
    </div>
  );
};
