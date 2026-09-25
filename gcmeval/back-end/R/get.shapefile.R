#Search and read a shapefile
get.shapefile <- function(filename,path=NULL,verbose=FALSE) {
  if(verbose) print("get.shapefile")
  if(filename!=basename(filename) & is.null(path)) {
    path <- dirname(filename)
    filename <- basename(filename)
  }
  fullname <- find.file(filename, path=path)[1]
  if(is.logical(fullname) && !fullname) {
    # Intento directo de resolución en el paquete o repositorio
    cand <- system.file("extdata", "SREX_regions", basename(filename), package = "gcmeval")
    if(file.exists(cand) && cand != "") {
      fullname <- cand
    } else {
      repo_cand <- file.path(getwd(), "gcmeval", "back-end", "inst", "extdata", "SREX_regions", basename(filename))
      if(file.exists(repo_cand)) fullname <- repo_cand
    }
  }
  shape <- sf::st_read(fullname)
  invisible(shape)
}
