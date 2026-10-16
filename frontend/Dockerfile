FROM node:24.8.0-alpine3.21

WORKDIR /app

RUN chown node:node .

USER node

COPY --chown=node:node \
    package.json \
    package-lock.json \
    .npmrc \
    ./

RUN npm install

COPY --chown=node:node . .

RUN npm install && \
    npm run build

EXPOSE 5173

CMD ["npx", "vite", "--host", "0.0.0.0"]
