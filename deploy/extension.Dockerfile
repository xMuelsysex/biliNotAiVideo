FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_ORIGIN
ENV VITE_API_ORIGIN=${VITE_API_ORIGIN}
RUN npm run build

FROM alpine:3.21 AS export
COPY --from=build /app/dist /dist
CMD ["sh", "-c", "rm -rf /out/* && cp -R /dist/. /out/"]
