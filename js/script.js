document.addEventListener("DOMContentLoaded", function() {

    // --- Theme Toggler ---
    const themeToggle = document.getElementById("theme-toggle");
    themeToggle.addEventListener("click", () => {
        const currentTheme = document.documentElement.getAttribute("data-theme");
        const newTheme = currentTheme === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", newTheme);
        localStorage.setItem("theme", newTheme);
    });

    // --- Mobile Menu ---
    const menuToggle = document.querySelector(".mobile-menu-toggle");
    const header = document.querySelector("header");
    const navLinks = document.querySelectorAll("header .main-nav ul li a");

    if (menuToggle && header) {
        menuToggle.addEventListener("click", () => {
            header.classList.toggle("nav-open");
            const isExpanded = header.classList.contains("nav-open");
            menuToggle.setAttribute("aria-expanded", isExpanded);
        });

        // Close menu when a link is clicked
        navLinks.forEach(link => {
            link.addEventListener('click', () => {
                if (header.classList.contains('nav-open')) {
                    header.classList.remove('nav-open');
                    menuToggle.setAttribute('aria-expanded', 'false');
                }
            });
        });
    }


    // --- Works Page Filter ---
    const filterContainer = document.querySelector(".works-filters");
    const worksGalleryItems = document.querySelectorAll(".full-works-grid .work-item");

    if (filterContainer) {
        filterContainer.addEventListener("click", (event) => {
            if (event.target.classList.contains("filter-btn")) {
                filterContainer.querySelector(".active").classList.remove("active");
                event.target.classList.add("active");
                const filterValue = event.target.getAttribute("data-filter");

                worksGalleryItems.forEach((item) => {
                    if (item.dataset.category === filterValue || filterValue === "all") {
                        item.style.display = "block";
                    } else {
                        item.style.display = "none";
                    }
                });
            }
        });
    }

    // --- Homepage Mini-Gallery Slider ---
    const galleryContainer = document.querySelector('.mini-gallery .gallery-container');
    if (galleryContainer) {
        const wrapper = galleryContainer.querySelector('.gallery-wrapper');
        const prevBtn = galleryContainer.querySelector('.prev');
        const nextBtn = galleryContainer.querySelector('.next');
        const items = wrapper.children;
        const middleIndex = Math.floor(items.length / 2);
        const heroSection = document.querySelector('.hero'); // Get the hero section

        const updateHeroBackground = () => {
            if (!heroSection) return; // Safety check

            const activeItem = wrapper.querySelector('.gallery-item.active');
            if (activeItem) {
                const activeImgSrc = activeItem.querySelector('img').src;
                // Set the CSS variable on the hero section
                heroSection.style.setProperty('--hero-bg-image-url', `url(${activeImgSrc})`);
            }
        };

        const updateActive = () => {
            for (let i = 0; i < items.length; i++) {
                if (i === middleIndex) {
                    items[i].classList.add('active');
                } else {
                    items[i].classList.remove('active');
                }
            }
            updateHeroBackground(); // Update the hero background whenever the active slide changes
        };

        const shiftItems = (direction) => {
            if (direction === 'next') {
                const firstItem = items[0];
                wrapper.appendChild(firstItem);
            } else if (direction === 'prev') {
                const lastItem = items[items.length - 1];
                wrapper.prepend(lastItem);
            }
            updateActive();
        };

        nextBtn.addEventListener('click', () => shiftItems('next'));
        prevBtn.addEventListener('click', () => shiftItems('prev'));

        // Initial setup
        updateActive();
    }

});