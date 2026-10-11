/** Shows the API's own error message (its `detail`) and a Retry button. */
export function ErrorBanner({ error, onRetry }: { error: Error | string; onRetry?: () => void }) {
  const message = typeof error === "string" ? error : error.message;
  return (
    <div className="error-banner" role="alert">
      <span>{message}</span>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
