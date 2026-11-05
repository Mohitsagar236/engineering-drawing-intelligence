// Cover browsers and bookmarks that still request the conventional favicon URL.
export function GET(request: Request) {
  return Response.redirect(new URL("/icon.svg", request.url), 308);
}
