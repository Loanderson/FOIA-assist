# Standard library only: no pip install, nothing fetched at runtime.
# Swap the base image for your agency's hardened Python image.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY foia_assist/ foia_assist/
COPY config/ config/
COPY data/ data/

USER app
EXPOSE 8080
# Bind to all interfaces inside the container; put the agency's SSO proxy in front.
CMD ["python", "-m", "foia_assist", "serve", "--host", "0.0.0.0", "--port", "8080"]
