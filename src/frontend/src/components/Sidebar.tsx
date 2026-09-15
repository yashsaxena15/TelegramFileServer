import { useState, useEffect } from "react";
import { 
  FolderOpen, Star, Trash2, 
  HardDrive, User, Settings, Download, Users, LogOut, Inbox, Laptop 
} from "lucide-react";
import { FileItem } from "./types";
import { useIsMobile } from "@/hooks/use-mobile";
import { api, UserProfile } from "@/lib/api";
import authService from "@/lib/authService";
import { useNavigate } from "react-router-dom";

interface SidebarProps {
  currentPath: string[];
  onNavigate: (filter: string) => void;
  onDrop: (item: any, targetFolder: string) => void;
  files: FileItem[];
  selectedFilter: string;
  activeView?: 'files' | 'profile' | 'settings' | 'users' | 'storage' | 'downloads';
  onNavigateView?: (view: 'files' | 'profile' | 'settings' | 'users' | 'storage' | 'downloads', filter?: string) => void;
  onOpenWebDAV?: () => void;
}

export const Sidebar = ({ 
  currentPath, 
  onNavigate, 
  onDrop, 
  files, 
  selectedFilter,
  activeView = 'files',
  onNavigateView,
  onOpenWebDAV
}: SidebarProps) => {
  const [dragOverFolder, setDragOverFolder] = useState<string | null>(null);
  const [isOwner, setIsOwner] = useState(false);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const isMobile = useIsMobile();
  const navigate = useNavigate();

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
  };

  const handleProfileOptionClick = (view: 'profile' | 'settings' | 'users' | 'storage' | 'downloads') => {
    if (onNavigateView) {
      onNavigateView(view);
    } else {
      navigate(`/${view}`);
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
  ];

  const profileOptions = [
    { id: "storage" as const, name: "Storage & Analytics", icon: HardDrive },
    { id: "profile" as const, name: "Profile", icon: User },
    { id: "settings" as const, name: "Settings", icon: Settings },
    { id: "downloads" as const, name: "Downloads", icon: Download },
    ...(isOwner ? [{ id: "users" as const, name: "Users", icon: Users }] : []),
  ];

  // Hide sidebar on mobile since mobile drawer will be used instead
  if (isMobile) {
    return null;
  }

  return (
    <div 
      className="w-64 bg-sidebar border-r border-sidebar-border flex flex-col relative select-none h-full shrink-0"
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      {/* Brand Header */}
      <div 
        className="py-4 px-4 border-b border-sidebar-border flex items-center gap-2.5 cursor-pointer"
        onClick={() => handleCategoryClick("all")}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        <div className="rounded-xl bg-primary/10 p-2 text-primary">
          <FolderOpen className="w-5 h-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="font-bold text-sidebar-foreground text-base tracking-tight leading-none truncate">
            Telegram Drive
          </h1>
          <p className="text-[11px] text-muted-foreground mt-1 leading-none">
            Cloud File Server
          </p>
        </div>
      </div>

      {/* Navigation list */}
      <nav 
        className="flex-1 overflow-y-auto py-2 custom-scrollbar"
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        {/* Category Filters */}
        <div className="px-4 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Categories
        </div>

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
                isSelected
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/50"
              } ${isDragOver ? "ring-2 ring-primary ring-inset" : ""}`}
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
            >
              <Icon className="w-4 h-4" />
              <span>{filter.name}</span>
            </button>
          );
        })}

        {/* User Profile Options - Combined right below Voice Messages */}
        <div className="my-2 border-t border-sidebar-border" />

        <div className="px-4 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Account
        </div>

        {profileOptions.map((item) => {
          const Icon = item.icon;
          const isSelected = activeView === item.id;

          return (
            <button
              key={item.id}
              onClick={() => handleProfileOptionClick(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all ${
                isSelected
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/50"
              }`}
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
            >
              <Icon className="w-4 h-4" />
              <span>{item.name}</span>
            </button>
          );
        })}

        {/* Integrations Section */}
        <div className="my-2 border-t border-sidebar-border" />

        <div className="px-4 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Integrations
        </div>

        <button
          onClick={() => {
            if (onOpenWebDAV) {
              onOpenWebDAV();
            } else {
              window.dispatchEvent(new CustomEvent('showWebDAVMount'));
            }
          }}
          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all text-sidebar-foreground hover:bg-sidebar-accent/50 group"
          title="Mount to RaiDrive, Windows Explorer, or MiXplorer"
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
        >
          <Laptop className="w-4 h-4 text-primary group-hover:scale-110 transition-transform" />
          <div className="flex items-center justify-between flex-1 min-w-0">
            <span className="truncate">Connect Drive</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium shrink-0">WebDAV</span>
          </div>
        </button>

        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all text-sidebar-foreground hover:bg-destructive/10 hover:text-destructive"
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
        >
          <LogOut className="w-4 h-4" />
          <span>Logout</span>
        </button>
      </nav>

      {/* User profile card at the bottom */}
      <div 
        className="p-3 border-t border-sidebar-border mt-auto bg-sidebar/40"
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        <div 
          onClick={() => handleProfileOptionClick("profile")}
          className="flex items-center gap-2.5 p-1.5 rounded-lg hover:bg-sidebar-accent/50 transition-colors cursor-pointer"
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
        </div>
      </div>
    </div>
  );
};