import { ShellProvider } from "@/components/shell/ShellProvider";
import { Sidebar } from "@/components/shell/Sidebar";
import { Header } from "@/components/shell/Header";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { ChatPanel } from "@/components/agents/Chat";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ShellProvider>
      <div className="flex h-full w-full bg-sidebarBg">
        <Sidebar />
        <main className="relative flex h-full min-w-0 flex-1 flex-col overflow-clip bg-appBg md:my-2 md:mr-2 md:h-[calc(100%-16px)] md:rounded-xl md:border md:border-borderDark md:shadow-xs">
          <Header />
          {children}
        </main>
      </div>
      <CommandPalette />
      <ChatPanel />
    </ShellProvider>
  );
}
