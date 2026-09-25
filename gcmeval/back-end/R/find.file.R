## Helper function to find files across Linux, Windows and macOS environments
find.file <- function(filename, path=NULL) {
  if(file.exists(filename)) {
    if(dirname(filename)==".") path <- getwd() else path <- dirname(filename)
    fullpath <- file.path(path, basename(filename))
    return(fullpath)
  }
  
  # Si se proporcionó un directorio de búsqueda existente
  if(!is.null(path) && dir.exists(path)) {
    matches <- list.files(path, pattern = paste0("^", basename(filename), "$"), recursive = TRUE, full.names = TRUE)
    if(length(matches) > 0) return(matches[1])
  }
  
  # Búsqueda en el paquete instalado gcmeval
  pkg_cand <- system.file("extdata", "SREX_regions", basename(filename), package = "gcmeval")
  if(file.exists(pkg_cand) && pkg_cand != "") return(pkg_cand)
  
  # Búsqueda en el directorio de trabajo del repositorio
  repo_cands <- c(
    file.path(getwd(), "gcmeval", "back-end", "inst", "extdata", "SREX_regions", basename(filename)),
    file.path(getwd(), "back-end", "inst", "extdata", "SREX_regions", basename(filename))
  )
  for(rc in repo_cands) {
    if(file.exists(rc)) return(rc)
  }
  
  return(FALSE)
}