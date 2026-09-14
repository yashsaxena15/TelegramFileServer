import { useState } from "react";
import { ChevronLeft, ChevronRight, Search, Grid3x3, List, RefreshCw, X } from "lucide-react";
import { Input } from "./ui/input";
import { Button } from "./ui/button";

interface TopBarProps {
  currentPath: string[];
  searchQuery: string;
  viewMode: "grid" | "list";
  onSearchChange: (query: string) => void;
  onViewModeChange: (mode: "grid" | "list") => void;
  onBack: () => void;
  onRefresh: () => void;
  onBreadcrumbClick: (index: number) => void;
}

export const TopBar = ({
  currentPath,
  searchQuery,
  viewMode,
  onSearchChange,
  onViewModeChange,
  onBack,
  onRefresh,
  onBreadcrumbClick,
}: TopBarProps) => {
  const [isMobileSearchOpen, setIsMobileSearchOpen] = useState(false);

  return (
    <div 
      className="backdrop-blur-md bg-background/70 border-b border-border select-none sticky top-0 z-10 shrink-0"
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      {isMobileSearchOpen ? (
        <div className="flex items-center gap-2 px-3 sm:px-4 py-2 w-full">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              autoFocus
              placeholder={`Search ${currentPath[currentPath.length - 1]}`}
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              className="pl-10 pr-9 h-9 bg-muted/50 border-0 rounded-lg text-sm"
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
            />
            {searchQuery && (
              <button
                onClick={() => onSearchChange("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsMobileSearchOpen(false)}
            className="text-xs px-2.5 h-9 shrink-0"
          >
            Cancel
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-2">
          {/* Navigation controls */}
          <div className="flex items-center gap-0.5 sm:gap-1 shrink-0">
            <Button
              variant="ghost"
              size="icon"
              onClick={onBack}
              className="h-8 w-8 rounded-lg transition-all duration-200 hover:bg-accent hover:scale-105"
              title="Back"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button 
              variant="ghost" 
              size="icon" 
              onClick={() => window.history.forward()}
              className="hidden sm:inline-flex h-8 w-8 rounded-lg transition-all duration-200 hover:bg-accent hover:scale-105"
              title="Forward"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={onRefresh}
              className="h-8 w-8 rounded-lg transition-all duration-200 hover:bg-accent hover:scale-105"
              title="Refresh"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>

          {/* Breadcrumbs */}
          <div 
            className="flex items-center gap-1 flex-1 min-w-0 bg-muted/50 backdrop-blur-sm rounded-lg px-2.5 sm:px-3 py-1.5 text-sm overflow-x-auto no-scrollbar whitespace-nowrap transition-all duration-200 hover:bg-muted/70"
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
          >
            {currentPath.map((folder, index) => (
              <div key={index} className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => onBreadcrumbClick(index)}
                  className="hover:text-primary transition-colors px-1 py-0.5 rounded transition-all duration-200 hover:bg-accent/50 max-w-[120px] sm:max-w-none truncate"
                >
                  {folder}
                </button>
                {index < currentPath.length - 1 && (
                  <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />
                )}
              </div>
            ))}
          </div>

          {/* Mobile search trigger */}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsMobileSearchOpen(true)}
            className="md:hidden h-8 w-8 shrink-0 rounded-lg transition-all duration-200 hover:bg-accent hover:scale-105"
            title="Search"
          >
            <Search className="h-4 w-4 text-muted-foreground" />
          </Button>

          {/* Desktop search bar */}
          <div 
            className="hidden md:block relative w-56 lg:w-64 shrink-0 transition-all duration-200 hover:scale-[1.01]"
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
          >
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={`Search ${currentPath[currentPath.length - 1]}`}
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              className="pl-10 h-9 bg-muted/50 border-0 backdrop-blur-sm rounded-lg transition-all duration-200 focus:ring-2 focus:ring-primary/50"
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
            />
          </div>

          {/* View mode toggle - placed at right side of search bar */}
          <div className="flex items-center gap-0.5 shrink-0 bg-muted/40 p-0.5 rounded-lg border border-border/40">
            <Button
              variant={viewMode === "grid" ? "secondary" : "ghost"}
              size="icon"
              onClick={() => onViewModeChange("grid")}
              className="h-7 w-7 rounded-md transition-all duration-150"
              title="Grid view"
            >
              <Grid3x3 className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant={viewMode === "list" ? "secondary" : "ghost"}
              size="icon"
              onClick={() => onViewModeChange("list")}
              className="h-7 w-7 rounded-md transition-all duration-150"
              title="List view"
            >
              <List className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};