import { FileExplorer } from "@/components/FileExplorer";
import { AuthWrapper } from "@/components/AuthWrapper";
import logger from "@/lib/logger";

const Index = () => {
  logger.info("Index page rendered");
  return (
    <AuthWrapper>
      <div className="flex flex-1 h-full w-full bg-background select-none min-h-0 overflow-hidden">
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <FileExplorer />
        </div>
      </div>
    </AuthWrapper>
  );
};

export default Index;