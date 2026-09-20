FROM rust:1-alpine AS build
RUN apk add --no-cache musl-dev
WORKDIR /src
COPY Cargo.toml ./
COPY src ./src
RUN cargo build --release

FROM scratch
COPY --from=build /src/target/release/container-echo /container-echo
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/container-echo"]
