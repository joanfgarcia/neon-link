import uvicorn


def main():
    """Entry point multiplataforma para Neon-Link."""
    print("Iniciando Neon-Link (Cross-Platform)...")
    uvicorn.run("neon_link.api.server:app", host="127.0.0.1", port=8770, reload=False)

if __name__ == "__main__":
    main()
