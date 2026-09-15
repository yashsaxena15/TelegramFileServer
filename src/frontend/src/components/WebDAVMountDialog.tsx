import React, { useState } from "react";
import { 
  Dialog, 
  DialogContent, 
  DialogDescription, 
  DialogHeader, 
  DialogTitle 
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { 
  Copy, 
  Check, 
  HardDrive, 
  Smartphone, 
  Laptop, 
  FolderOpen, 
  ShieldCheck, 
  Zap, 
  ExternalLink,
  Info
} from "lucide-react";

interface WebDAVMountDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  username?: string;
}

export const WebDAVMountDialog: React.FC<WebDAVMountDialogProps> = ({
  open,
  onOpenChange,
  username = "admin"
}) => {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const hostname = window.location.hostname || "127.0.0.1";
  const port = window.location.port || (window.location.protocol === "https:" ? "443" : "80");
  const protocol = window.location.protocol;
  const webdavUrl = `${protocol}//${hostname}${port && !["80", "443"].includes(port) ? `:${port}` : ""}/webdav`;

  const copyToClipboard = (key: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto bg-background/95 backdrop-blur-md border border-border shadow-2xl p-6 rounded-2xl">
        <DialogHeader className="space-y-2">
          <div className="flex items-center gap-2.5">
            <div className="p-2.5 rounded-xl bg-primary/10 text-primary">
              <HardDrive className="w-6 h-6" />
            </div>
            <div>
              <DialogTitle className="text-xl font-bold flex items-center gap-2">
                Mount Drive (WebDAV Server)
                <Badge variant="secondary" className="text-xs bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                  Live RFC 4918
                </Badge>
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground mt-0.5">
                Mount your Telegram Drive directly into Windows Explorer, macOS Finder, or Android MiXplorer.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* Highlight features pill */}
        <div className="grid grid-cols-3 gap-2 py-1 text-center">
          <div className="bg-muted/40 rounded-lg p-2 flex flex-col items-center justify-center border border-border/50">
            <Zap className="w-4 h-4 text-amber-500 mb-1" />
            <span className="text-[11px] font-semibold">Multi-Bot Parallel</span>
            <span className="text-[10px] text-muted-foreground">High speed streaming</span>
          </div>
          <div className="bg-muted/40 rounded-lg p-2 flex flex-col items-center justify-center border border-border/50">
            <FolderOpen className="w-4 h-4 text-primary mb-1" />
            <span className="text-[11px] font-semibold">4 Virtual Folders</span>
            <span className="text-[10px] text-muted-foreground">Home, Inbox, Starred, Trash</span>
          </div>
          <div className="bg-muted/40 rounded-lg p-2 flex flex-col items-center justify-center border border-border/50">
            <ShieldCheck className="w-4 h-4 text-emerald-500 mb-1" />
            <span className="text-[11px] font-semibold">Read & Write</span>
            <span className="text-[10px] text-muted-foreground">Upload, Rename & Stream</span>
          </div>
        </div>

        <Tabs defaultValue="details" className="w-full mt-2">
          <TabsList className="grid grid-cols-3 w-full bg-muted/50 p-1 rounded-xl">
            <TabsTrigger value="details" className="text-xs">
              <Info className="w-3.5 h-3.5 mr-1.5" /> Connection Info
            </TabsTrigger>
            <TabsTrigger value="raidrive" className="text-xs">
              <Laptop className="w-3.5 h-3.5 mr-1.5" /> RaiDrive (PC)
            </TabsTrigger>
            <TabsTrigger value="mixplorer" className="text-xs">
              <Smartphone className="w-3.5 h-3.5 mr-1.5" /> MiXplorer (Android)
            </TabsTrigger>
          </TabsList>

          {/* TAB 1: CONNECTION INFO */}
          <TabsContent value="details" className="space-y-3 pt-2">
            <div className="space-y-2.5">
              {/* Full URL */}
              <div className="bg-muted/30 border border-border rounded-xl p-3 flex items-center justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">WebDAV URL</p>
                  <p className="text-sm font-mono font-medium truncate text-foreground select-all mt-0.5">{webdavUrl}</p>
                </div>
                <Button 
                  size="sm" 
                  variant="outline" 
                  onClick={() => copyToClipboard("url", webdavUrl)}
                  className="shrink-0 h-8 gap-1.5"
                >
                  {copiedKey === "url" ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                  <span className="text-xs">{copiedKey === "url" ? "Copied" : "Copy"}</span>
                </Button>
              </div>

              {/* Host & Port grid */}
              <div className="grid grid-cols-2 gap-2.5">
                <div className="bg-muted/30 border border-border rounded-xl p-3 flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">Server / Host</p>
                    <p className="text-sm font-mono font-medium truncate text-foreground select-all mt-0.5">{hostname}</p>
                  </div>
                  <Button 
                    size="icon" 
                    variant="ghost" 
                    className="h-8 w-8 shrink-0" 
                    onClick={() => copyToClipboard("host", hostname)}
                  >
                    {copiedKey === "host" ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                  </Button>
                </div>

                <div className="bg-muted/30 border border-border rounded-xl p-3 flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">Port</p>
                    <p className="text-sm font-mono font-medium truncate text-foreground select-all mt-0.5">{port || "80"}</p>
                  </div>
                  <Button 
                    size="icon" 
                    variant="ghost" 
                    className="h-8 w-8 shrink-0" 
                    onClick={() => copyToClipboard("port", port || "80")}
                  >
                    {copiedKey === "port" ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                  </Button>
                </div>
              </div>

              {/* Path & Username */}
              <div className="grid grid-cols-2 gap-2.5">
                <div className="bg-muted/30 border border-border rounded-xl p-3 flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">Path</p>
                    <p className="text-sm font-mono font-medium truncate text-foreground select-all mt-0.5">/webdav</p>
                  </div>
                  <Button 
                    size="icon" 
                    variant="ghost" 
                    className="h-8 w-8 shrink-0" 
                    onClick={() => copyToClipboard("path", "/webdav")}
                  >
                    {copiedKey === "path" ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                  </Button>
                </div>

                <div className="bg-muted/30 border border-border rounded-xl p-3 flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">Username</p>
                    <p className="text-sm font-mono font-medium truncate text-foreground select-all mt-0.5">{username}</p>
                  </div>
                  <Button 
                    size="icon" 
                    variant="ghost" 
                    className="h-8 w-8 shrink-0" 
                    onClick={() => copyToClipboard("user", username)}
                  >
                    {copiedKey === "user" ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                  </Button>
                </div>
              </div>

              {/* Password notice */}
              <div className="rounded-xl bg-amber-500/10 border border-amber-500/20 p-3 flex items-start gap-2.5">
                <Info className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                <div className="text-xs text-amber-900 dark:text-amber-200">
                  <span className="font-semibold">Password: </span> 
                  Use the same password you use to log into this web application.
                </div>
              </div>
            </div>
          </TabsContent>

          {/* TAB 2: RAIDRIVE (WINDOWS / DESKTOP) */}
          <TabsContent value="raidrive" className="space-y-3 pt-2 text-xs">
            <Card className="border-border">
              <CardContent className="p-4 space-y-3">
                <div className="flex items-center justify-between border-b pb-2">
                  <span className="font-semibold text-sm">Setup Guide: RaiDrive for Windows</span>
                  <Badge variant="outline" className="text-[10px]">Recommended Virtual Drive</Badge>
                </div>

                <ol className="space-y-2.5 list-decimal list-inside text-muted-foreground leading-relaxed">
                  <li>
                    Download and open <strong className="text-foreground">RaiDrive</strong> on your Windows PC.
                  </li>
                  <li>
                    Click <strong className="text-foreground">+ Add</strong> at the top bar.
                  </li>
                  <li>
                    Select <strong className="text-foreground">NAS</strong> category and choose <strong className="text-foreground">WebDAV</strong>.
                  </li>
                  <li>
                    Uncheck the <strong className="text-foreground">Address</strong> checkbox to enter custom host and port.
                  </li>
                  <li>
                    Enter <strong className="text-foreground font-mono">{hostname}</strong> in the host field, and port <strong className="text-foreground font-mono">{port || "80"}</strong>.
                  </li>
                  <li>
                    Set Path to: <strong className="text-foreground font-mono">/webdav</strong>
                  </li>
                  <li>
                    Account: Enter your Username (<strong className="text-foreground">{username}</strong>) and your web login Password.
                  </li>
                  <li>
                    Click <strong className="text-foreground">Connect</strong>. Your Telegram Drive will mount as a drive letter (e.g. <strong className="text-foreground font-mono">Z:</strong>)!
                  </li>
                </ol>

                <div className="bg-muted/50 rounded-lg p-2.5 text-[11px] text-muted-foreground">
                  💡 <strong className="text-foreground">Tip:</strong> In RaiDrive, you will see four root folders: 
                  <code className="mx-1 px-1 py-0.5 bg-background rounded text-primary">Home</code>, 
                  <code className="mx-1 px-1 py-0.5 bg-background rounded text-primary">Telegram Inbox</code>, 
                  <code className="mx-1 px-1 py-0.5 bg-background rounded text-primary">Starred</code>, and 
                  <code className="mx-1 px-1 py-0.5 bg-background rounded text-primary">Trash</code>. 
                  You can drag-and-drop any file to upload directly to Telegram!
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* TAB 3: MIXPLORER (ANDROID) */}
          <TabsContent value="mixplorer" className="space-y-3 pt-2 text-xs">
            <Card className="border-border">
              <CardContent className="p-4 space-y-3">
                <div className="flex items-center justify-between border-b pb-2">
                  <span className="font-semibold text-sm">Setup Guide: MiXplorer for Android</span>
                  <Badge variant="outline" className="text-[10px]">Mobile File Manager</Badge>
                </div>

                <ol className="space-y-2.5 list-decimal list-inside text-muted-foreground leading-relaxed">
                  <li>
                    Open <strong className="text-foreground">MiXplorer</strong> on your Android phone.
                  </li>
                  <li>
                    Open the left side drawer (☰) and tap <strong className="text-foreground">+ Add Storage</strong>.
                  </li>
                  <li>
                    Select <strong className="text-foreground">WebDAV</strong> from the cloud storage list.
                  </li>
                  <li>
                    Display Name: <strong className="text-foreground font-mono">Telegram Drive</strong>
                  </li>
                  <li>
                    Host / Server: <strong className="text-foreground font-mono">{hostname}</strong>
                  </li>
                  <li>
                    Port: <strong className="text-foreground font-mono">{port || "80"}</strong>
                  </li>
                  <li>
                    Path: <strong className="text-foreground font-mono">/webdav</strong>
                  </li>
                  <li>
                    Enter your Username (<strong className="text-foreground font-mono">{username}</strong>) and web Password.
                  </li>
                  <li>
                    Tap <strong className="text-foreground">Save</strong> and tap the bookmark to browse and stream files smoothly!
                  </li>
                </ol>

                <div className="bg-muted/50 rounded-lg p-2.5 text-[11px] text-muted-foreground">
                  🎬 <strong className="text-foreground">Media Playback:</strong> In MiXplorer or VLC, video files stream instantly with fast forward / rewind seeking without downloading the whole file first!
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        <div className="pt-2 flex justify-end">
          <Button variant="default" onClick={() => onOpenChange(false)} className="px-5">
            Done
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
export default WebDAVMountDialog;
