# 1. build the static site (stdlib Python only)
FROM python:3.12-slim AS build
WORKDIR /src
COPY site.json .
COPY engine ./engine
COPY books ./books
RUN python engine/build.py --check

# 2. serve it
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
