import { useToast } from "@/components/ui/use-toast";
import { Toast, ToastTitle, ToastDescription } from "@/components/ui/toast";

export function Toaster() {
  const { toasts, dismiss } = useToast();

  return (
    <div className="fixed top-4 right-4 z-50 flex max-h-screen w-full max-w-sm flex-col-reverse gap-2 pointer-events-none">
      {toasts.map(function ({ id, title, description, variant }) {
        return (
          <Toast key={id} variant={variant} onClose={() => dismiss(id)}>
            <div className="grid gap-1">
              {title && <ToastTitle>{title}</ToastTitle>}
              {description && (
                <ToastDescription>{description}</ToastDescription>
              )}
            </div>
          </Toast>
        );
      })}
    </div>
  );
}
