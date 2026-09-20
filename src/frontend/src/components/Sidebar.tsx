import { useState, useEffect } from "react";
import { 
  FolderOpen, Star, Trash2, 
  HardDrive, User, Settings, Users, LogOut, Inbox, Laptop,
  ArrowUpDown, X, PanelLeft, ShieldCheck
} from "lucide-react";
import { FileItem } from "./types";
import { useIsMobile } from "@/hooks/use-mobile";
import { api, UserProfile } from "@/lib/api";
import authService from "@/lib/authService";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useTransferManager } from "@/hooks/useTransferManager";

interface SidebarProps {
  currentPath: string[];
  onNavigate: (filter: string) => void;
  onDrop: (item: any, targetFolder: string) => void;
  files: FileItem[];
  selectedFilter: string;
  activeView?: 'files' | 'profile' | 'settings' | 'users' | 'storage' | 'transfers' | 'downloads';
  onNavigateView?: (view: 'files' | 'profile' | 'settings' | 'users' | 'storage' | 'transfers' | 'downloads', filter?: string) => void;
  onOpenWebDAV?: () => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
  onNewFolder?: () => void;
  onUploadFiles?: () => void;
  onUploadFolder?: () => void;
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
}

export const Sidebar = ({ 
  currentPath, 
  onNavigate, 
  onDrop, 
  files, 
  selectedFilter,
  activeView = 'files',
  onNavigateView,
  onOpenWebDAV,
  isCollapsed = false,
  onToggleCollapse,
  onNewFolder,
  onUploadFiles,
  onUploadFolder,
  mobileOpen = false,
  onCloseMobile
}: SidebarProps) => {
  const [dragOverFolder, setDragOverFolder] = useState<string | null>(null);
  const [isOwner, setIsOwner] = useState(false);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { totalActiveCount } = useTransferManager();

  useEffect(() => {
    api.isUserOwner()
      .then(res => setIsOwner(res.is_owner))
      .catch(() => setIsOwner(false));

    api.fetchUserProfile()
      .then(setUserProfile)
      .catch(() => {});
  }, []);

  const handleDragOver = (e: React.DragEvent, folderPath: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOverFolder(folderPath);
  };

  const handleDragLeave = () => {
    setDragOverFolder(null);
  };

  const handleDrop = (e: React.DragEvent, folderPath: string) => {
    e.preventDefault();
    e.stopPropagation();

    try {
      const itemData = e.dataTransfer.getData("application/json");
      if (itemData) {
        const item = JSON.parse(itemData);
        onDrop(item, folderPath);
      }
    } catch (error) {
      // Failed to parse dropped item
    }

    setDragOverFolder(null);
  };

  const handleCategoryClick = (filter: string) => {
    if (onNavigateView) {
      onNavigateView('files', filter);
    } else {
      onNavigate(filter);
    }
    if (isMobile && onCloseMobile) {
      onCloseMobile();
    }
  };

  const handleProfileOptionClick = (view: 'profile' | 'settings' | 'users' | 'storage' | 'transfers') => {
    if (onNavigateView) {
      onNavigateView(view);
    } else {
      navigate(`/${view}`);
    }
    if (isMobile && onCloseMobile) {
      onCloseMobile();
    }
  };

  const handleLogout = async () => {
    try {
      await authService.logout();
    } finally {
      navigate("/login");
    }
  };

  const categoryFilters = [
    { name: "Home", icon: FolderOpen, filter: "all" },
    { name: "Telegram Inbox", icon: Inbox, filter: "inbox" },
    { name: "Starred", icon: Star, filter: "starred" },
    { name: "Trash", icon: Trash2, filter: "trash" },
    { name: "Private Vault", icon: ShieldCheck, filter: "vault" },
  ];

  const profileOptions = [
    { id: "transfers" as const, name: "Transfers", icon: ArrowUpDown, badge: totalActiveCount > 0 ? totalActiveCount : null },
    { id: "storage" as const, name: "Storage & Analytics", icon: HardDrive },
    { id: "profile" as const, name: "Profile", icon: User },
    { id: "settings" as const, name: "Settings", icon: Settings },
    ...(isOwner ? [{ id: "users" as const, name: "Users", icon: Users, badge: null }] : []),
  ];

  // Render content function shared between desktop and mobile drawer
  const renderSidebarContent = (collapsed: boolean) => (
    <div className="flex flex-col h-full w-full select-none">
      {/* Brand Header */}
      <div 
        className={`py-4 px-3.5 border-b border-sidebar-border flex items-center justify-between cursor-pointer ${
          collapsed ? "justify-center px-2" : ""
        }`}
        onClick={() => handleCategoryClick("all")}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="rounded-xl bg-primary/10 p-2 text-primary shrink-0">
            <FolderOpen className="w-5 h-5" />
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <h1 className="font-bold text-sidebar-foreground text-base tracking-tight leading-none truncate">
                Telegram Drive
              </h1>
              <p className="text-[11px] text-muted-foreground mt-1 leading-none">
                Cloud File Server
              </p>
            </div>
          )}
        </div>

        {/* Mobile close button */}
        {isMobile && onCloseMobile && (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-muted-foreground"
            onClick={(e) => {
              e.stopPropagation();
              onCloseMobile();
            }}
          >
            <X className="w-4 h-4" />
          </Button>
        )}
      </div>



      {/* Navigation list */}
      <nav className="flex-1 overflow-y-auto py-2 custom-scrollbar">
        {/* Category Filters */}
        {!collapsed && (
          <div className="px-4 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Categories
          </div>
        )}

        {categoryFilters.map((filter) => {
          const Icon = filter.icon;
          const isSelected = activeView === 'files' && selectedFilter === filter.filter;
          const isDragOver = dragOverFolder === filter.filter;

          return (
            <button
              key={filter.filter}
              onClick={() => handleCategoryClick(filter.filter)}
              onDragOver={(e) => handleDragOver(e, filter.filter)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, filter.filter)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all ${
                collapsed ? "justify-center px-2 py-3" : ""
              } ${
                isSelected
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/50"
              } ${isDragOver ? "ring-2 ring-primary ring-inset" : ""}`}
              title={collapsed ? filter.name : undefined}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {!collapsed && <span>{filter.name}</span>}
            </button>
          );
        })}

        {/* System & Tools Section */}
        <div className="my-2 border-t border-sidebar-border" />
        {!collapsed && (
          <div className="px-4 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Navigation
          </div>
        )}

        {profileOptions.map((item) => {
          const Icon = item.icon;
          const isSelected = activeView === item.id || (item.id === 'transfers' && activeView === 'downloads');

          return (
            <button
              key={item.id}
              onClick={() => handleProfileOptionClick(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all relative ${
                collapsed ? "justify-center px-2 py-3" : ""
              } ${
                isSelected
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/50"
              }`}
              title={collapsed ? item.name : undefined}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {!collapsed && (
                <div className="flex items-center justify-between flex-1 min-w-0">
                  <span className="truncate">{item.name}</span>
                  {item.badge && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary text-primary-foreground font-semibold">
                      {item.badge}
                    </span>
                  )}
                </div>
              )}
              {collapsed && item.badge && (
                <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-primary animate-pulse" />
              )}
            </button>
          );
        })}

        {/* Integrations Section */}
        <div className="my-2 border-t border-sidebar-border" />
        {!collapsed && (
          <div className="px-4 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Integrations
          </div>
        )}

        <button
          onClick={() => {
            if (onOpenWebDAV) {
              onOpenWebDAV();
            } else {
              window.dispatchEvent(new CustomEvent('showWebDAVMount'));
            }
            if (isMobile && onCloseMobile) onCloseMobile();
          }}
          className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all text-sidebar-foreground hover:bg-sidebar-accent/50 group ${
            collapsed ? "justify-center px-2 py-3" : ""
          }`}
          title="Mount to RaiDrive, Windows Explorer, or MiXplorer"
        >
          <Laptop className="w-4 h-4 text-primary group-hover:scale-110 transition-transform shrink-0" />
          {!collapsed && (
            <div className="flex items-center justify-between flex-1 min-w-0">
              <span className="truncate">Connect Drive</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium shrink-0">WebDAV</span>
            </div>
          )}
        </button>

        <button
          onClick={handleLogout}
          className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all text-sidebar-foreground hover:bg-destructive/10 hover:text-destructive ${
            collapsed ? "justify-center px-2 py-3" : ""
          }`}
          title={collapsed ? "Logout" : undefined}
        >
          <LogOut className="w-4 h-4 shrink-0" />
          {!collapsed && <span>Logout</span>}
        </button>
      </nav>

      {/* User profile card at the bottom */}
      <div className="p-2.5 border-t border-sidebar-border mt-auto bg-sidebar/40">
        <div 
          onClick={() => handleProfileOptionClick("profile")}
          className={`flex items-center gap-2.5 p-1.5 rounded-lg hover:bg-sidebar-accent/50 transition-colors cursor-pointer ${
            collapsed ? "justify-center p-1" : ""
          }`}
          title="Open Profile"
        >
          <div className="w-8 h-8 rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold text-xs shrink-0 overflow-hidden">
            {userProfile?.telegram_profile_picture ? (
              <img 
                src={userProfile.telegram_profile_picture} 
                alt={userProfile.username} 
                className="w-full h-full object-cover" 
              />
            ) : (
              (userProfile?.username || "U").charAt(0).toUpperCase()
            )}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-sidebar-foreground truncate leading-tight">
                {userProfile?.telegram_first_name 
                  ? `${userProfile.telegram_first_name} ${userProfile.telegram_last_name || ''}`.trim()
                  : (userProfile?.username || "User")}
              </p>
              <p className="text-[10px] text-muted-foreground truncate leading-tight mt-0.5">
                {userProfile?.email || (isOwner ? "Admin / Owner" : "Online")}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  // Mobile Drawer with Backdrop
  if (isMobile) {
    if (!mobileOpen) return null;

    return (
      <div className="fixed inset-0 z-50 flex">
        <div 
          className="fixed inset-0 bg-black/60 backdrop-blur-xs animate-in fade-in duration-200"
          onClick={onCloseMobile}
        />
        <div className="relative z-50 w-72 h-full bg-sidebar border-r border-sidebar-border shadow-2xl flex flex-col animate-in slide-in-from-left duration-200">
          {renderSidebarContent(false)}
        </div>
      </div>
    );
  }

  // Desktop Collapsible Sidebar
  return (
    <div 
      className={`${
        isCollapsed ? "w-16" : "w-64"
      } bg-sidebar border-r border-sidebar-border flex flex-col relative select-none h-full shrink-0 transition-all duration-300 ease-in-out`}
    >
      {renderSidebarContent(isCollapsed)}
    </div>
  );
};