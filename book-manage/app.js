(() => {
  const countValue = document.getElementById("count-value");
  const incrementButton = document.getElementById("increment-btn");
  let count = 0;

  const render = () => {
    countValue.textContent = String(count);
  };

  incrementButton.addEventListener("click", () => {
    count += 1;
    render();
  });

  render();
})();
