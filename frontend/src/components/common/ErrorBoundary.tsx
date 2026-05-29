import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * ErrorBoundary — catches render-time exceptions anywhere below it so a single
 * broken component never blanks the whole app. Mirrors the backend's Rule 8
 * philosophy on the client: the user sees a friendly message and a recovery
 * action, never a raw stack trace.
 */
interface State {
  hasError: boolean;
  message: string | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, message: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Log to the console for developers; production wiring would forward to
    // Application Insights. Never surfaced to the user verbatim.
    console.error("Unhandled UI error", error, info.componentStack);
  }

  private handleReset = () => {
    this.setState({ hasError: false, message: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex h-full flex-col items-center justify-center p-10 text-center">
          <div className="mb-4 flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
            <AlertTriangle className="size-6" />
          </div>
          <h2 className="text-lg font-semibold">Something went wrong</h2>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            This part of the page failed to load. You can try again — if it keeps
            happening, refresh the app.
          </p>
          <Button className="mt-5" onClick={this.handleReset}>
            Try again
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
